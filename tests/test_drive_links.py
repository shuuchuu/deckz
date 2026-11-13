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
from deckz.exceptions import DeckzError, InvalidConfigurationError

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

    # The user's, outside the repository, by the deck's path in it.
    registry = repo.parent / "user" / "drive-links" / "company" / "abc.yml"
    assert settings.paths.drive_links == registry
    text = registry.read_text(encoding="utf8")
    assert "pdf/en/abc-handout.pdf: file-id" in text
    assert drive_links.load(settings) == {pdf: "file-id"}
    assert drive_links.links(settings) == {
        pdf: "https://drive.google.com/file/d/file-id/view"
    }


def test_every_checkout_shares_the_registry(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    drive_links.save(settings, {settings.paths.pdf_dir / "abc-handout.pdf": "id"})
    other = repo.parent / "other-checkout"
    copytree(repo, other)

    other_settings = DeckSettings.from_yaml(_deck_dir(other))

    assert drive_links.load(other_settings) == {
        other_settings.paths.pdf_dir / "abc-handout.pdf": "id"
    }


def test_a_malformed_registry_is_refused(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    settings.paths.drive_links.parent.mkdir(parents=True)
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


def test_parse_file_id() -> None:
    file_id = "1CHFEpdqK0YadnuFeISCmgtIDdyyp2yH4"
    for given in (
        f"https://drive.google.com/file/d/{file_id}/view?usp=sharing",
        f"https://drive.google.com/open?id={file_id}",
        file_id,
    ):
        assert drive_links.parse_file_id(given) == file_id
    assert drive_links.parse_file_id("handout") is None


def _adoptions(repo: Path, *requests: str) -> dict[Path, str]:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    pdf_dir = settings.paths.pdf_dir
    pdfs = [pdf_dir / "abc-handout.pdf", pdf_dir / "abc-print-handout.pdf"]
    return drive_links.adoptions(settings, pdfs, requests)


def test_adoptions_take_paths_in_the_deck_or_the_repository(repo: Path) -> None:
    pdf_dir = DeckSettings.from_yaml(_deck_dir(repo)).paths.pdf_dir
    link = "https://drive.google.com/file/d/handout-file-id/view"

    assert _adoptions(
        repo,
        f"pdf/abc-handout.pdf={link}",
        "company/abc/pdf/abc-print-handout.pdf=print-file-id",
    ) == {
        pdf_dir / "abc-handout.pdf": "handout-file-id",
        pdf_dir / "abc-print-handout.pdf": "print-file-id",
    }


def test_adoptions_refuse_what_they_cant_reserve(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    handout = settings.paths.pdf_dir / "abc-handout.pdf"
    printed = settings.paths.pdf_dir / "abc-print-handout.pdf"
    for requests, problem in (
        (("pdf/abc-handout.pdf",), "give `<pdf>=<Drive link>`"),
        (("pdf/abc-handout.pdf=nope",), "give `<pdf>=<Drive link>`"),
        (("pdf/en/abc-handout.pdf=file-id-0001",), "the deck builds no"),
        (
            ("pdf/abc-handout.pdf=file-id-0001", "pdf/abc-handout.pdf=file-id-0002"),
            "is given two links",
        ),
        (
            (
                "pdf/abc-handout.pdf=file-id-0001",
                "pdf/abc-print-handout.pdf=file-id-0001",
            ),
            "would share one Drive file",
        ),
    ):
        with raises(DeckzError, match=problem):
            _adoptions(repo, *requests)

    drive_links.save(settings, {handout: "file-id-0001"})
    # Its own link again: nothing to do.
    assert _adoptions(repo, "pdf/abc-handout.pdf=file-id-0001") == {}
    with raises(DeckzError, match="has a link already"):
        _adoptions(repo, "pdf/abc-handout.pdf=file-id-0002")
    with raises(DeckzError, match="would share one Drive file"):
        _adoptions(repo, "pdf/abc-print-handout.pdf=file-id-0001")
    assert printed not in drive_links.load(settings)


def test_reserve_dry_run_shows_the_links_given(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    found = _json(
        capsys,
        "upload",
        "--reserve",
        "--dry-run",
        "--json",
        "--link",
        "pdf/abc-handout.pdf=https://drive.google.com/file/d/handout-file-id/view",
    )
    assert "company/abc/pdf/abc-handout.pdf" in found["reserve"]
    assert found["link"] == {"company/abc/pdf/abc-handout.pdf": "handout-file-id"}

    capsys.readouterr()
    main(
        (
            "upload",
            "--reserve",
            "--dry-run",
            "--link",
            "pdf/abc-handout.pdf=a-file-id-0001",
        )
    )
    out = capsys.readouterr().out
    assert "company/abc/pdf/abc-handout.pdf (link: a-file-id-0001)" in out


def test_link_needs_reserve(repo: Path, caplog: Any) -> None:
    with raises(SystemExit):
        main(("upload", "--dry-run", "--link", "pdf/abc-handout.pdf=a-file-id-0001"))
    assert "pass it with --reserve" in caplog.text
