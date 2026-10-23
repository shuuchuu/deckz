import json
from pathlib import Path
from shutil import copytree
from typing import Any

import appdirs
from pygit2 import init_repository
from pytest import CaptureFixture, fixture, raises

from deckz import drive_links
from deckz.cli import main
from deckz.configuring.settings import DeckSettings
from deckz.exceptions import InvalidConfigurationError

_NOTES_TEMPLATE = "= Course notes\n"


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    repo = tmp_path / "data"
    copytree(Path(__file__).parent / "test_cli_typst", repo)
    init_repository(str(repo))
    (repo / "templates" / "jinja2" / "course-notes.typ").write_text(
        _NOTES_TEMPLATE, encoding="utf8"
    )
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.chdir(repo / "company" / "abc")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(user_dir))
    return repo


def _deck_dir(repo: Path) -> Path:
    return repo / "company" / "abc"


def _json(capsys: CaptureFixture[str], *args: str) -> Any:
    capsys.readouterr()
    main(args)
    return json.loads(capsys.readouterr().out)


def test_registry_round_trip(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    pdf = settings.paths.pdf_dir / "en" / "abc-handout.pdf"
    assert drive_links.load(settings) == {}

    drive_links.save(settings, {pdf: "file-id"})

    text = settings.paths.drive_links.read_text(encoding="utf8")
    assert "pdf/en/abc-handout.pdf: file-id" in text
    assert drive_links.load(settings) == {pdf: "file-id"}
    assert drive_links.links(settings) == {
        pdf: "https://drive.google.com/file/d/file-id/view"
    }


def test_a_malformed_registry_is_refused(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    settings.paths.drive_links.write_text("- a\n", encoding="utf8")

    with raises(InvalidConfigurationError, match="Drive file ID"):
        drive_links.load(settings)


def test_reserve_lists_every_pdf_and_the_course_notes(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    found = _json(capsys, "upload", "--reserve", "--dry-run", "--json")
    assert "company/abc/pdf/abc-handout.pdf" in found["reserve"]
    assert "company/abc/pdf/abc-print-handout.pdf" in found["reserve"]
    assert not any("course-notes" in pdf for pdf in found["reserve"])

    chapter = repo / "course-notes" / "greeting" / "hello.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# Hello\n\nAt length.\n", encoding="utf8")
    found = _json(capsys, "upload", "--reserve", "--dry-run", "--json")
    assert "company/abc/pdf/course-notes/abc-course-notes.pdf" in found["reserve"]

    settings = DeckSettings.from_yaml(_deck_dir(repo))
    drive_links.save(settings, {settings.paths.pdf_dir / "abc-handout.pdf": "id"})
    found = _json(capsys, "upload", "--reserve", "--dry-run", "--json")
    assert "company/abc/pdf/abc-handout.pdf" not in found["reserve"]


def test_upload_finds_pdfs_built_before_their_links(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    main(("run", "--handout", "--no-presentation", "--no-print"))
    found = _json(capsys, "upload", "--dry-run", "--json", "--skip-checks")
    assert found["outdated"] == found["unlinked"] == found["unbuilt"] == []

    settings = DeckSettings.from_yaml(_deck_dir(repo))
    handout = settings.paths.pdf_dir / "abc-handout.pdf"
    printed = settings.paths.pdf_dir / "abc-print-handout.pdf"
    drive_links.save(settings, {handout: "handout-id", printed: "print-id"})
    found = _json(capsys, "upload", "--dry-run", "--json", "--skip-checks")

    # Every PDF shows the handout's link now, and only it has one.
    assert "company/abc/pdf/abc-handout.pdf" in found["outdated"]
    assert "company/abc/pdf/abc-handout.pdf" not in found["unlinked"]
    assert found["unlinked"]
    assert found["unbuilt"] == ["company/abc/pdf/abc-print-handout.pdf"]
    with raises(SystemExit):
        main(("upload", "--skip-checks"))
