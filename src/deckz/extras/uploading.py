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


class Uploader:
    def __init__(self, settings: DeckSettings):
        self._logger = getLogger(__name__)
        self._settings = settings
        self._service = self._build_service()
        folder_id, folder_link = self._check_folders()
        backup_id = self._create_backup(folder_id)
        self._upload(folder_id)
        if backup_id:
            self._logger.info("Deleting backup of old files")
            self._service.files().delete(fileId=backup_id).execute()
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

    def _create_backup(self, folder_id: str) -> str | None:
        file_ids = self._list(folder=False, parents=[folder_id], name=None)
        backup_id = None
        if file_ids:
            self._logger.info("Creating backup of current files")
            old_backup_info = self._get(folder=True, parents=[folder_id], name="backup")
            if old_backup_info is not None:
                old_backup_id = old_backup_info.get("id")
                self._service.files().update(
                    fileId=old_backup_id, body={"name": "backup-old"}
                ).execute()
            backup_id, _ = self._create_folder(parent=folder_id, name="backup")
            for file_id in file_ids:
                self._service.files().update(
                    fileId=file_id, addParents=backup_id, removeParents=folder_id
                ).execute()
            if old_backup_info is not None:
                old_backup_id = old_backup_info.get("id")
                self._service.files().delete(fileId=old_backup_id).execute()
        return backup_id

    def _upload(self, folder_id: str) -> dict[Path, str]:
        self._logger.info("Uploading pdfs")
        pdfs = sorted(
            (self._settings.paths.pdf_dir).glob("*.pdf"), key=lambda p: p.name
        )
        links: dict[Path, str] = {}
        progress = self._build_progress()
        with progress:
            for pdf in pdfs:
                pdf_size = pdf.stat().st_size
                file_metadata = {"name": pdf.name, "parents": [folder_id]}
                media = MediaFileUpload(
                    str(pdf),
                    chunksize=256 * 1024,
                    mimetype="application/pdf",
                    resumable=True,
                )
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

    def _list(
        self,
        folder: bool | None,
        parents: list[str],
        name: str | None,
    ) -> list[str]:
        return [item.get("id") for item in self._query(folder, parents, name)]

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
                    fields="nextPageToken, files(id,webViewLink)",
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        return results
