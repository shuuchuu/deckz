import json
from hashlib import md5
from logging import getLogger
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

import httplib2
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from pytest import MonkeyPatch, raises

from deckz.exceptions import DeckzError
from deckz.extras import uploading
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
                gdrive_secrets=pdf_dir.parent / "gdrive-secrets.json",
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


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def test_upload_refuses_a_reserved_file_gone(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    service = build_service(existing_files=[])
    service.files.return_value.get.return_value.execute.side_effect = http_error(404)
    uploader = build_uploader(pdf_dir, service)

    with raises(DeckzError, match="gone from Drive"):
        upload_dir(uploader, pdf_dir, {a: "reserved-a"})


def test_upload_refuses_a_reserved_file_in_the_trash(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    service = build_service(existing_files=[])
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "reserved-a",
        "name": "a.pdf",
        "webViewLink": "...",
        "trashed": True,
    }
    uploader = build_uploader(pdf_dir, service)

    with raises(DeckzError, match="Drive's trash"):
        upload_dir(uploader, pdf_dir, {a: "reserved-a"})


def test_upload_writes_to_a_reserved_file_outside_the_folder(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    # An adopted file, where its owner put it, under another name.
    service = build_service(existing_files=[])
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "adopted-id",
        "name": "old-handout.pdf",
        "webViewLink": "...",
        "trashed": False,
    }
    uploader = build_uploader(pdf_dir, service)

    upload_dir(uploader, pdf_dir, {a: "adopted-id"})

    _, kwargs = service.files.return_value.update.call_args
    assert kwargs["fileId"] == "adopted-id"
    assert "body" not in kwargs  # Its name stays.
    service.files.return_value.create.assert_not_called()
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


def adoptable_service(meta: dict[str, Any], *, reachable: bool = True) -> MagicMock:
    service = build_service(existing_files=[])
    service.files.return_value.get.return_value.execute.side_effect = [
        {"id": meta["id"]} if reachable else http_error(404),
        meta,
    ]
    return service


PDF_META = {
    "id": "adopted-id",
    "name": "handout.pdf",
    "mimeType": "application/pdf",
    "trashed": False,
    "capabilities": {"canEdit": True},
}


def adopt(
    tmp_path: Path, monkeypatch: MonkeyPatch, service: MagicMock
) -> tuple[MagicMock, dict[Path, str]]:
    """`uploading.adopt` on one PDF, Drive replaced by `service`, the Picker mocked.

    Returns:
        The Picker's mock, and what `adopt` returns.
    """
    picker = MagicMock()
    monkeypatch.setattr(uploading, "_build_service", lambda _: service)
    monkeypatch.setattr(uploading, "_pick", picker)
    settings = build_uploader(tmp_path / "pdf", service)._settings
    return picker, uploading.adopt(settings, {tmp_path / "a.pdf": "adopted-id"})


def test_adopt_shares_a_reachable_pdf_without_the_picker(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    service = adoptable_service(PDF_META)

    picker, ids = adopt(tmp_path, monkeypatch, service)

    assert ids == {tmp_path / "a.pdf": "adopted-id"}
    picker.assert_not_called()
    service.permissions.return_value.create.assert_called_once_with(
        fileId="adopted-id", body={"type": "anyone", "role": "reader"}
    )


def test_adopt_opens_the_picker_for_a_file_out_of_reach(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    service = adoptable_service(PDF_META, reachable=False)

    picker, _ = adopt(tmp_path, monkeypatch, service)

    _, file_ids = picker.call_args.args
    assert file_ids == ["adopted-id"]


def test_adopt_refuses_what_isnt_an_editable_pdf(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    for meta in (
        PDF_META | {"mimeType": "application/vnd.google-apps.document"},
        PDF_META | {"capabilities": {"canEdit": False}},
        PDF_META | {"trashed": True},
    ):
        service = adoptable_service(meta)

        with raises(DeckzError, match="isn't a PDF you can edit"):
            adopt(tmp_path, monkeypatch, service)
        service.permissions.return_value.create.assert_not_called()


def test_adopt_refuses_a_file_still_out_of_reach(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    service = build_service(existing_files=[])
    service.files.return_value.get.return_value.execute.side_effect = http_error(404)

    with raises(DeckzError, match="still out of reach"):
        adopt(tmp_path, monkeypatch, service)


def pick(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    file_ids: list[str],
    answer: Any,
) -> list[str]:
    """Run `_pick`, the browser replaced by `answer(query)`'s redirect query.

    Returns:
        The codes it exchanged for a token.
    """
    (tmp_path / "gdrive-secrets.json").write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client-id",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf8",
    )
    fetched: list[str] = []
    monkeypatch.setattr(
        InstalledAppFlow, "fetch_token", lambda _, code: fetched.append(code)
    )

    def browse(url: str) -> None:
        query = {
            key: values[0] for key, values in parse_qs(urlparse(url).query).items()
        }
        redirect = f"{query['redirect_uri']}?{urlencode(answer(query))}"
        Thread(target=lambda: urlopen(redirect).read(), daemon=True).start()

    monkeypatch.setattr(uploading.webbrowser, "open", browse)
    uploading._pick(build_uploader(tmp_path / "pdf", MagicMock())._settings, file_ids)
    return fetched


def test_pick_asks_for_the_files_and_checks_they_were_picked(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    asked: dict[str, str] = {}

    def answer(query: dict[str, str]) -> dict[str, str]:
        asked.update(query)
        return {
            "state": query["state"],
            "code": "the-code",
            "picked_file_ids": query["file_ids"],
        }

    assert pick(tmp_path, monkeypatch, ["id-1", "id-2"], answer) == ["the-code"]
    assert asked["trigger_onepick"] == "true"
    assert asked["file_ids"] == "id-1,id-2"
    assert asked["allow_multiple"] == "true"
    assert asked["scope"] == "https://www.googleapis.com/auth/drive.file"


def test_pick_refuses_a_file_not_picked(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def answer(query: dict[str, str]) -> dict[str, str]:
        return {"state": query["state"], "code": "c", "picked_file_ids": "id-1"}

    with raises(DeckzError, match="weren't picked: id-2"):
        pick(tmp_path, monkeypatch, ["id-1", "id-2"], answer)


def test_pick_refuses_an_error_or_a_wrong_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    for redirect in (
        {"error": "access_denied"},
        {"state": "forged", "code": "c", "picked_file_ids": "id-1"},
    ):
        with raises(DeckzError, match="Google Picker API"):
            pick(tmp_path, monkeypatch, ["id-1"], lambda _, r=redirect: r)


def test_upload_updates_the_aliases_and_never_deletes_them(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdf"
    a = write_pdf(pdf_dir, "a.pdf")
    local = md5(a.read_bytes()).hexdigest()
    service = build_service(
        existing_files=[
            {"id": "reserved-a", "name": "a.pdf", "webViewLink": "..."},
            # An alias in the deck's folder, with no PDF of its name.
            {"id": "alias-here", "name": "a-all.pdf", "webViewLink": "..."},
        ]
    )
    metas = {
        "alias-here": {"name": "a-all.pdf", "md5Checksum": "old"},
        "alias-same": {"name": "a-same.pdf", "md5Checksum": local},
        "alias-trashed": {"name": "a-gone.pdf", "trashed": True},
    }

    def get(fileId: str, fields: str) -> MagicMock:  # ruff: ignore[invalid-argument-name]
        request = MagicMock()
        if fileId == "alias-gone":
            request.execute.side_effect = http_error(404)
        else:
            request.execute.return_value = {
                "id": fileId,
                "webViewLink": "...",
                "trashed": False,
            } | metas[fileId]
        return request

    service.files.return_value.get.side_effect = get
    uploader = build_uploader(pdf_dir, service)
    uploader._by_folder = lambda pdfs: {None: list(pdfs)}  # type: ignore[method-assign]
    uploader._subfolder = lambda _: FOLDER_ID  # type: ignore[method-assign]

    uploader.upload(
        [a],
        {a: "reserved-a"},
        {a: ["alias-here", "alias-same", "alias-trashed", "alias-gone"]},
    )

    updated = [
        kwargs["fileId"]
        for _, kwargs in service.files.return_value.update.call_args_list
    ]
    assert updated == ["reserved-a", "alias-here"]
    service.files.return_value.delete.assert_not_called()
