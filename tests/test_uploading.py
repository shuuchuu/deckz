from hashlib import md5
from logging import getLogger
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from pytest import raises

from deckz.exceptions import DeckzError
from deckz.extras.uploading import Uploader, _RemoteFile

if TYPE_CHECKING:
    from deckz.configuring.settings import DeckSettings

FOLDER_ID = "folder-1"


def build_uploader(pdf_dir: Path, service: MagicMock) -> Uploader:
    uploader = Uploader.__new__(Uploader)
    uploader._logger = getLogger(__name__)
    uploader._settings = cast(
        "DeckSettings",
        SimpleNamespace(
            paths=SimpleNamespace(
                pdf_dir=pdf_dir,
                course_notes_pdf_dir=pdf_dir / "course-notes",
                drive_links=pdf_dir.parent / "drive-links.yml",
            )
        ),
    )
    uploader._service = service
    uploader._folder_id = FOLDER_ID
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
) -> Path:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / name).write_bytes(content)
    return pdf_dir / name


def upload_dir(
    uploader: Uploader, pdf_dir: Path, ids: dict[Path, str] | None = None
) -> dict[Path, str]:
    return uploader._upload(FOLDER_ID, sorted(pdf_dir.glob("*.pdf")), ids or {})


def test_upload_creates_new_file(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    write_pdf(pdf_dir, "a.pdf")
    service = build_service(existing_files=[])
    uploader = build_uploader(pdf_dir, service)

    upload_dir(uploader, pdf_dir)

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

    upload_dir(uploader, pdf_dir)

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

    upload_dir(uploader, pdf_dir)

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

    upload_dir(uploader, pdf_dir)

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

    links = upload_dir(uploader, pdf_dir)

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

    upload_dir(uploader, pdf_dir)

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

    upload_dir(uploader, pdf_dir)

    service.files.return_value.delete.assert_not_called()


def test_upload_writes_to_the_reserved_file_and_keeps_reserved_orphans(
    tmp_path: Path,
) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    service = build_service(
        existing_files=[
            # Same name, but not the reserved file: an orphan.
            {"id": "other-id", "name": "a.pdf", "webViewLink": "..."},
            {"id": "reserved-a", "name": "a.pdf", "webViewLink": "..."},
            # Reserved, not built here: its link is printed, it stays.
            {"id": "reserved-b", "name": "b.pdf", "webViewLink": "..."},
        ]
    )
    uploader = build_uploader(pdf_dir, service)

    upload_dir(uploader, pdf_dir, {a: "reserved-a", pdf_dir / "b.pdf": "reserved-b"})

    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["fileId"] == "reserved-a"
    service.files.return_value.delete.assert_called_once_with(fileId="other-id")


def test_upload_refuses_a_reserved_file_gone(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    uploader = build_uploader(pdf_dir, build_service(existing_files=[]))

    with raises(DeckzError, match="not in the deck's folder anymore"):
        upload_dir(uploader, pdf_dir, {a: "reserved-a"})


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
        "a.pdf": _RemoteFile(
            id="id-1", name="a.pdf", web_view_link="...", md5_checksum=None
        ),
        "b.pdf": _RemoteFile(
            id="id-2", name="b.pdf", web_view_link="...", md5_checksum=None
        ),
    }


def test_upload_sends_english_pdfs_and_course_notes_to_their_folders(
    tmp_path: Path,
) -> None:
    pdf_dir = tmp_path / "pdf"
    pdfs = [
        write_pdf(pdf_dir, "a.pdf"),
        write_pdf(pdf_dir / "course-notes", "a-notes.pdf"),
        write_pdf(pdf_dir / "en", "a.pdf"),
        write_pdf(pdf_dir / "course-notes" / "en", "a-notes.pdf"),
    ]
    service = build_service(existing_files=[])
    service.files.return_value.create.return_value.execute.return_value = {
        "id": "en-folder",
        "webViewLink": "...",
    }
    uploader = build_uploader(pdf_dir, service)

    links = uploader.upload(pdfs, {})

    bodies = [
        kwargs["body"] for _, kwargs in service.files.return_value.create.call_args_list
    ]
    # By name in each folder.
    assert bodies == [
        {"name": "a-notes.pdf", "parents": [FOLDER_ID]},
        {"name": "a.pdf", "parents": [FOLDER_ID]},
        {
            "name": "en",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [FOLDER_ID],
        },
        {"name": "a-notes.pdf", "parents": ["en-folder"]},
        {"name": "a.pdf", "parents": ["en-folder"]},
    ]
    assert set(links) == set(pdfs)


def test_upload_without_english_pdfs_skips_en_subfolder(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    service = build_service(existing_files=[])
    uploader = build_uploader(pdf_dir, service)

    uploader.upload([a], {})

    service.files.return_value.create.assert_called_once()
    _, kwargs = service.files.return_value.create.call_args
    assert kwargs["body"] == {"name": "a.pdf", "parents": [FOLDER_ID]}


def test_reserve_keeps_online_files_and_creates_the_others(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    online, new, known = pdf_dir / "a.pdf", pdf_dir / "b.pdf", pdf_dir / "c.pdf"
    service = build_service(
        existing_files=[{"id": "online-id", "name": "a.pdf", "webViewLink": "..."}]
    )
    service.files.return_value.create.return_value.execute.return_value = {
        "id": "empty-id"
    }
    uploader = build_uploader(pdf_dir, service)

    ids = uploader.reserve([online, new], {known: "known-id"})

    assert ids == {known: "known-id", online: "online-id", new: "empty-id"}
    _, kwargs = service.files.return_value.create.call_args
    assert kwargs["body"] == {
        "name": "b.pdf",
        "parents": [FOLDER_ID],
        "mimeType": "application/pdf",
    }
