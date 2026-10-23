from collections.abc import Iterable, Mapping, Set
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
from ..models import LANGS, lang_dir


@dataclass
class _RemoteFile:
    id: str
    name: str
    web_view_link: str
    md5_checksum: str | None


class Uploader:
    """The deck's Google Drive folder, `deckz/<deck path>/`, shared read-only.

    English PDFs go to its `en/` subfolder, the course notes next to the \
    slides of their language. A PDF with a reserved file (`deckz.drive_links`) \
    is written to it, so its link never changes; the others go to the file \
    of the same name.
    """

    def __init__(self, settings: DeckSettings):
        self._logger = getLogger(__name__)
        self._settings = settings
        self._service = self._build_service()
        self._folder_id, self.folder_link = self._check_folders()

    def reserve(self, pdfs: Iterable[Path], ids: Mapping[Path, str]) -> dict[Path, str]:
        """A Drive file for each of `pdfs` that `ids` has none for.

        A PDF already online keeps its file, and so the link it had; for \
        the others, an empty file is created, which `upload` fills later.

        Args:
            pdfs: The PDFs, absolute paths.
            ids: The deck's registry, each PDF's Drive file ID.

        Returns:
            `ids`, with the new files.
        """
        reserved = dict(ids)
        for subfolder, folder_pdfs in self._by_folder(
            pdf for pdf in pdfs if pdf not in ids
        ).items():
            folder_id = self._subfolder(subfolder)
            existing = self._existing_files_by_name(folder_id)
            for pdf in folder_pdfs:
                if (remote := existing.get(pdf.name)) is not None:
                    self._logger.info(f"“{pdf.name}” is online: keeping its link")
                    reserved[pdf] = remote.id
                    continue
                self._logger.info(f"Reserving “{pdf.name}”")
                created = (
                    self._service.files()
                    .create(
                        body={
                            "name": pdf.name,
                            "parents": [folder_id],
                            "mimeType": "application/pdf",
                        },
                        fields="id",
                    )
                    .execute()
                )
                reserved[pdf] = created.get("id")
        return reserved

    def upload(self, pdfs: Iterable[Path], ids: Mapping[Path, str]) -> dict[Path, str]:
        """Upload `pdfs`, each to its reserved file if `ids` has one.

        Args:
            pdfs: The PDFs, absolute paths.
            ids: The deck's registry, each PDF's Drive file ID.

        Returns:
            Each PDF's link.
        """
        links: dict[Path, str] = {}
        for subfolder, folder_pdfs in self._by_folder(pdfs).items():
            links |= self._upload(self._subfolder(subfolder), folder_pdfs, ids)
        return links

    def _by_folder(self, pdfs: Iterable[Path]) -> dict[str | None, list[Path]]:
        # Each PDF's remote subfolder, by the language directory it's in:
        # none for French, `en` for English.
        paths = self._settings.paths
        folders: dict[str | None, list[Path]] = {}
        for pdf in pdfs:
            for lang in LANGS:
                dirs = (paths.pdf_dir, paths.course_notes_pdf_dir)
                if any(pdf.parent == lang_dir(directory, lang) for directory in dirs):
                    subfolder = None if lang == LANGS[0] else lang
                    folders.setdefault(subfolder, []).append(pdf)
                    break
            else:
                msg = f"{pdf} is in none of the deck's PDF directories"
                raise DeckzError(msg)
        return folders

    def _subfolder(self, name: str | None) -> str:
        if name is None:
            return self._folder_id
        folder_id, _ = self._get_or_create_folder(self._folder_id, name)
        return folder_id

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
            self._settings.paths.gdrive_credentials.parent.mkdir(
                parents=True, exist_ok=True
            )
            with self._settings.paths.gdrive_credentials.open("wb") as fh:
                pickle_dump(creds, fh)

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _check_folders(self) -> tuple[str, str]:
        self._logger.info("Checking/creating folder hierarchy")
        folders = [app_name]
        folders.extend(self._settings.paths.deck_path.parts)
        parent = "root"
        for folder in folders:
            folder_id, folder_link = self._get_or_create_folder(parent, folder)
            parent = folder_id
        self._logger.debug(f"Setting permissions for {folder}")
        self._service.permissions().create(
            fileId=folder_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        return folder_id, folder_link

    def _get_or_create_folder(self, parent: str, name: str) -> tuple[str, str]:
        folder_info = self._get(folder=True, parents=[parent], name=name)
        if folder_info is None:
            created = self._create_folder(parent, name)
            self._logger.debug(f"“{name}” folder was created")
            return created
        self._logger.debug(f"“{name}” folder was present")
        return folder_info.get("id"), folder_info.get("webViewLink")

    def _existing_files(self, folder_id: str) -> list[_RemoteFile]:
        return [
            _RemoteFile(
                id=item.get("id"),
                name=item.get("name"),
                web_view_link=item.get("webViewLink"),
                md5_checksum=item.get("md5Checksum"),
            )
            for item in self._query(folder=False, parents=[folder_id], name=None)
        ]

    def _existing_files_by_name(self, folder_id: str) -> dict[str, _RemoteFile]:
        existing: dict[str, _RemoteFile] = {}
        for remote in self._existing_files(folder_id):
            if remote.name in existing:
                self._logger.warning(
                    f"Found several files named “{remote.name}”, only the first one "
                    "will be considered for updates"
                )
            else:
                existing[remote.name] = remote
        return existing

    @staticmethod
    def _local_md5(pdf: Path) -> str:
        hasher = md5()
        with pdf.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _upload(
        self, folder_id: str, pdfs: Iterable[Path], ids: Mapping[Path, str]
    ) -> dict[Path, str]:
        pdfs = sorted(pdfs, key=lambda p: p.name)
        self._logger.info(f"Uploading {len(pdfs)} pdfs")
        remote_files = self._existing_files(folder_id)
        existing_by_id = {remote.id: remote for remote in remote_files}
        existing_by_name = self._existing_files_by_name(folder_id)
        remaining = {remote.id for remote in remote_files}
        links: dict[Path, str] = {}
        progress = self._build_progress()
        with progress:
            for pdf in pdfs:
                if pdf in ids:
                    existing = self._reserved_file(pdf, ids[pdf], existing_by_id)
                else:
                    existing = existing_by_name.get(pdf.name)
                if existing is not None:
                    remaining.discard(existing.id)
                    if existing.md5_checksum == self._local_md5(pdf):
                        self._logger.info(f"“{pdf.name}” is unchanged, skipping upload")
                        links[pdf] = existing.web_view_link
                        continue
                links[pdf] = self._send(pdf, existing, folder_id, progress)
        if not pdfs:
            self._logger.warning(
                "No local pdfs found, skipping deletion of remote files to avoid "
                "wiping the whole remote folder"
            )
        else:
            self._delete_orphans(
                [remote for remote in remote_files if remote.id in remaining],
                set(ids.values()),
            )
        return links

    def _reserved_file(
        self, pdf: Path, file_id: str, existing_by_id: Mapping[str, _RemoteFile]
    ) -> _RemoteFile:
        if (existing := existing_by_id.get(file_id)) is None:
            msg = (
                f"“{pdf.name}”'s Drive file ({file_id}, in "
                f"{self._settings.paths.drive_links}) is not in the deck's "
                "folder anymore: restore it from Drive's trash, or remove its "
                "line and run `deckz upload --reserve` for a new link, then "
                "rebuild the PDFs showing it"
            )
            raise DeckzError(msg)
        return existing

    def _send(
        self,
        pdf: Path,
        existing: _RemoteFile | None,
        folder_id: str,
        progress: Progress,
    ) -> str:
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
                    advance=int((status.progress() - previous_progress) * pdf_size),
                )
                previous_progress = status.progress()
        progress.update(task, completed=pdf_size)
        return response.get("webViewLink")

    def _delete_orphans(
        self, orphans: Iterable[_RemoteFile], reserved: Set[str]
    ) -> None:
        for remote in orphans:
            if remote.id in reserved:
                # Its link may be printed in PDFs already handed out.
                self._logger.info(
                    f"Keeping “{remote.name}”, with no local PDF: its link is reserved"
                )
                continue
            self._logger.info(f"Deleting orphaned remote file “{remote.name}”")
            self._service.files().delete(fileId=remote.id).execute()

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
