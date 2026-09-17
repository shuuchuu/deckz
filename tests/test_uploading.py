from hashlib import md5
from logging import getLogger
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from deckz.extras.uploading import Uploader, _RemoteFile

if TYPE_CHECKING:
    from deckz.configuring.settings import DeckSettings

FOLDER_ID = "folder-1"


def build_uploader(pdf_dir: Path, service: MagicMock) -> Uploader:
    uploader = Uploader.__new__(Uploader)
    uploader._logger = getLogger(__name__)
    uploader._settings = cast(
        "DeckSettings", SimpleNamespace(paths=SimpleNamespace(pdf_dir=pdf_dir))
    )
    uploader._service = service
    return uploader


def build_service(existing_files: list[dict[str, str]]) -> MagicMock:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": existing_files,
        "nextPageToken": None,
    }

    def next_chunk() -> tuple[None, dict[str, str]]:
        return None, {"id": "new-id", "webViewLink": "http://example.com/new-id"}

    service.files.return_value.create.return_value.next_chunk.side_effect = next_chunk
    service.files.return_value.update.return_value.next_chunk.side_effect = next_chunk
    return service


def write_pdf(
    pdf_dir: Path, name: str, content: bytes = b"%PDF-1.4 fake content"
) -> None:
    pdf_dir.mkdir(exist_ok=True)
    (pdf_dir / name).write_bytes(content)


def test_upload_creates_new_file(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "a.pdf")
    service = build_service(existing_files=[])
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    service.files.return_value.create.assert_called_once()
    _, kwargs = service.files.return_value.create.call_args
    assert kwargs["body"] == {"name": "a.pdf", "parents": [FOLDER_ID]}
    service.files.return_value.update.assert_not_called()
    service.files.return_value.delete.assert_not_called()


def test_upload_updates_existing_file(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "b.pdf")
    service = build_service(
        existing_files=[{"id": "existing-id", "name": "b.pdf", "webViewLink": "..."}]
    )
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    service.files.return_value.update.assert_called_once()
    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["fileId"] == "existing-id"
    assert "body" not in kwargs
    service.files.return_value.create.assert_not_called()
    service.files.return_value.delete.assert_not_called()


def test_upload_deletes_orphaned_remote_file(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "a.pdf")
    service = build_service(
        existing_files=[{"id": "orphan-id", "name": "c.pdf", "webViewLink": "..."}]
    )
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    service.files.return_value.delete.assert_called_once_with(fileId="orphan-id")


def test_upload_mixed_scenario(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "a.pdf")
    write_pdf(pdf_dir, "b.pdf")
    service = build_service(
        existing_files=[
            {"id": "existing-id", "name": "b.pdf", "webViewLink": "..."},
            {"id": "orphan-id", "name": "c.pdf", "webViewLink": "..."},
        ]
    )
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    _, create_kwargs = service.files.return_value.create.call_args
    assert create_kwargs["body"] == {"name": "a.pdf", "parents": [FOLDER_ID]}
    _, update_kwargs = service.files.return_value.update.call_args
    assert update_kwargs["fileId"] == "existing-id"
    service.files.return_value.delete.assert_called_once_with(fileId="orphan-id")


def test_upload_skips_unchanged_file(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    content = b"%PDF-1.4 unchanged content"
    write_pdf(pdf_dir, "b.pdf", content)
    checksum = md5(content).hexdigest()
    service = build_service(
        existing_files=[
            {
                "id": "existing-id",
                "name": "b.pdf",
                "webViewLink": "http://example.com/existing-id",
                "md5Checksum": checksum,
            }
        ]
    )
    uploader = build_uploader(pdf_dir, service)

    links = uploader._upload(FOLDER_ID)

    service.files.return_value.update.assert_not_called()
    service.files.return_value.create.assert_not_called()
    service.files.return_value.delete.assert_not_called()
    assert links[pdf_dir / "b.pdf"] == "http://example.com/existing-id"


def test_upload_updates_changed_file_despite_matching_name(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "b.pdf", b"%PDF-1.4 new content")
    service = build_service(
        existing_files=[
            {
                "id": "existing-id",
                "name": "b.pdf",
                "webViewLink": "...",
                "md5Checksum": md5(b"%PDF-1.4 old content").hexdigest(),
            }
        ]
    )
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    service.files.return_value.update.assert_called_once()
    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["fileId"] == "existing-id"


def test_upload_empty_local_dir_skips_deletion(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    service = build_service(
        existing_files=[{"id": "orphan-id", "name": "c.pdf", "webViewLink": "..."}]
    )
    uploader = build_uploader(pdf_dir, service)

    uploader._upload(FOLDER_ID)

    service.files.return_value.delete.assert_not_called()


def test_existing_files_by_name_paginates(tmp_path: Path) -> None:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [{"id": "id-1", "name": "a.pdf", "webViewLink": "..."}],
            "nextPageToken": "page-2",
        },
        {
            "files": [{"id": "id-2", "name": "b.pdf", "webViewLink": "..."}],
            "nextPageToken": None,
        },
    ]
    uploader = build_uploader(tmp_path / "pdf", service)

    result = uploader._existing_files_by_name(FOLDER_ID)

    assert result == {
        "a.pdf": _RemoteFile(id="id-1", web_view_link="...", md5_checksum=None),
        "b.pdf": _RemoteFile(id="id-2", web_view_link="...", md5_checksum=None),
    }
