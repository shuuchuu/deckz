from dataclasses import dataclass
from hashlib import md5
from logging import getLogger
from pathlib import Path
from pickle import dump as pickle_dump
from pickle import load as pickle_load
from typing import Any

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from .. import app_name
from ..configuring.settings import DeckSettings
from ..exceptions import DeckzError


@dataclass
class _RemoteFile:
    id: str
    web_view_link: str
    md5_checksum: str | None


class Uploader:
    def __init__(self, settings: DeckSettings):
        self._logger = getLogger(__name__)
        self._settings = settings
        self._service = self._build_service()
        folder_id, folder_link = self._check_folders()
        self._upload(folder_id)
        print(f"Online folder: {folder_link}")

    @staticmethod
    def _build_progress() -> Progress:
        return Progress(
            TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
        )

    @staticmethod
    def _build_task(progress: Progress, filename: str, size: int) -> TaskID:
        return progress.add_task("upload", filename=filename, total=size)

    def _build_service(self) -> Any:
        if self._settings.paths.gdrive_credentials.is_file():
            with self._settings.paths.gdrive_credentials.open("rb") as fh:
                creds = pickle_load(fh)
        else:
            creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._settings.paths.gdrive_secrets,
                    ["https://www.googleapis.com/auth/drive.file"],
                )
                creds = flow.run_local_server(port=0)
            with self._settings.paths.gdrive_credentials.open("wb") as fh:
                pickle_dump(creds, fh)

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _check_folders(self) -> tuple[str, str]:
        self._logger.info("Checking/creating folder hierarchy")
        folders = [app_name]
        folders.extend(
            self._settings.paths.current_dir.relative_to(
                self._settings.paths.git_dir
            ).parts
        )
        parent = "root"
        for folder in folders:
            folder_info = self._get(folder=True, parents=[parent], name=folder)
            if folder_info is None:
                folder_id, folder_link = self._create_folder(parent, folder)
                self._logger.debug(f"“{folder}” folder was created")
            else:
                folder_id, folder_link = (
                    folder_info.get("id"),
                    folder_info.get("webViewLink"),
                )
                self._logger.debug(f"“{folder}” folder was present")
            parent = folder_id
        self._logger.debug(f"Setting permissions for {folder}")
        self._service.permissions().create(
            fileId=folder_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        return folder_id, folder_link

    def _existing_files_by_name(self, folder_id: str) -> dict[str, _RemoteFile]:
        existing: dict[str, _RemoteFile] = {}
        for item in self._query(folder=False, parents=[folder_id], name=None):
            name = item.get("name")
            if name in existing:
                self._logger.warning(
                    f"Found several files named “{name}”, only the first one will "
                    "be considered for updates"
                )
            else:
                existing[name] = _RemoteFile(
                    id=item.get("id"),
                    web_view_link=item.get("webViewLink"),
                    md5_checksum=item.get("md5Checksum"),
                )
        return existing

    @staticmethod
    def _local_md5(pdf: Path) -> str:
        hasher = md5()
        with pdf.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _upload(self, folder_id: str) -> dict[Path, str]:
        self._logger.info("Uploading pdfs")
        pdfs = sorted(
            (self._settings.paths.pdf_dir).glob("*.pdf"), key=lambda p: p.name
        )
        existing_by_name = self._existing_files_by_name(folder_id)
        remaining_remote_names = set(existing_by_name)
        links: dict[Path, str] = {}
        progress = self._build_progress()
        with progress:
            for pdf in pdfs:
                remaining_remote_names.discard(pdf.name)
                existing = existing_by_name.get(pdf.name)
                if existing is not None and existing.md5_checksum == self._local_md5(
                    pdf
                ):
                    self._logger.info(f"“{pdf.name}” is unchanged, skipping upload")
                    links[pdf] = existing.web_view_link
                    continue
                pdf_size = pdf.stat().st_size
                media = MediaFileUpload(
                    str(pdf),
                    chunksize=256 * 1024,
                    mimetype="application/pdf",
                    resumable=True,
                )
                if existing is not None:
                    self._logger.debug(f"Updating existing file “{pdf.name}”")
                    request = self._service.files().update(
                        fileId=existing.id, media_body=media, fields="id,webViewLink"
                    )
                else:
                    self._logger.debug(f"Creating new file “{pdf.name}”")
                    file_metadata = {"name": pdf.name, "parents": [folder_id]}
                    request = self._service.files().create(
                        body=file_metadata, media_body=media, fields="id,webViewLink"
                    )
                response = None
                task = self._build_task(progress, pdf.name, pdf_size)
                previous_progress = 0
                while response is None:
                    status, response = request.next_chunk()
                    if status and previous_progress != status.progress():
                        progress.update(
                            task,
                            advance=int(
                                (status.progress() - previous_progress) * pdf_size
                            ),
                        )
                        previous_progress = status.progress()
                progress.update(task, completed=pdf_size)
                links[pdf] = response.get("webViewLink")
        if not pdfs:
            self._logger.warning(
                "No local pdfs found, skipping deletion of remote files to avoid "
                "wiping the whole remote folder"
            )
        else:
            for name in remaining_remote_names:
                self._logger.info(f"Deleting orphaned remote file “{name}”")
                self._service.files().delete(fileId=existing_by_name[name].id).execute()
        return links

    def _create_folder(self, parent: str, name: str) -> tuple[str, str]:
        file_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        file = (
            self._service.files()
            .create(body=file_metadata, fields="id,webViewLink")
            .execute()
        )
        return file.get("id"), file.get("webViewLink")

    def _get(
        self, folder: bool | None, parents: list[str], name: str | None
    ) -> Any | None:
        results = self._query(folder, parents, name)
        if len(results) > 1:
            msg = "found several files while trying to retrieve one"
            raise DeckzError(msg)
        return results[0] if results else None

    def _query(self, folder: bool | None, parents: list[str], name: str | None) -> Any:
        page_token = None
        results = []
        query_conditions = ["trashed = false"]
        if folder is not None:
            query_conditions.append(
                f"mimeType {'=' if folder else '!='} "
                "'application/vnd.google-apps.folder'"
            )
        for parent in parents:
            query_conditions.append(f"'{parent}' in parents")
        if name is not None:
            query_conditions.append(f"name = '{name}'")
        query = " and ".join(query_conditions)
        while True:
            response = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id,name,webViewLink,md5Checksum)",
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        return results
