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
from deckz.pipelines import published_pdfs, published_targets

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
    assert "pass them with --reserve" in caplog.text


def _links_file(repo: Path, entries: dict[str, str]) -> Path:
    path = repo.parent / "links.yml"
    path.write_text(
        "".join(f"{key}: {value}\n" for key, value in entries.items()),
        encoding="utf8",
    )
    return path


def test_links_file_groups_the_requests_by_deck(repo: Path) -> None:
    copytree(_deck_dir(repo), repo / "company" / "xyz")
    path = _links_file(
        repo,
        {
            "company/abc/pdf/abc-handout.pdf": "file-id-0001",
            "company/xyz/pdf/xyz-handout.pdf": "file-id-0002",
            "company/xyz/pdf/en/xyz-handout.pdf": "file-id-0003",
        },
    )

    assert drive_links.links_file(path, repo) == {
        repo / "company" / "abc": ["company/abc/pdf/abc-handout.pdf=file-id-0001"],
        repo / "company" / "xyz": [
            "company/xyz/pdf/xyz-handout.pdf=file-id-0002",
            "company/xyz/pdf/en/xyz-handout.pdf=file-id-0003",
        ],
    }


def test_links_file_refuses_what_it_cant_reserve(repo: Path) -> None:
    for entries, problem in (
        ({"pdf/abc-handout.pdf": "file-id-0001"}, "is in no deck"),
        (
            {
                "company/abc/pdf/abc-handout.pdf": "file-id-0001",
                "company/abc/pdf/abc-print-handout.pdf": "file-id-0001",
            },
            "would share one Drive file",
        ),
    ):
        with raises(DeckzError, match=problem):
            drive_links.links_file(_links_file(repo, entries), repo)
    path = repo.parent / "links.yml"
    path.write_text("- company/abc/pdf/abc-handout.pdf\n", encoding="utf8")
    with raises(DeckzError, match="should map each PDF's path"):
        drive_links.links_file(path, repo)
    with raises(DeckzError, match="no such file"):
        drive_links.links_file(repo.parent / "missing.yml", repo)


def test_reserve_with_a_links_file_covers_every_deck_it_names(
    repo: Path, capsys: CaptureFixture[str], monkeypatch: Any
) -> None:
    xyz = repo / "company" / "xyz"
    copytree(_deck_dir(repo), xyz)
    deck_yml = xyz / "deck.yml"
    deck_yml.write_text(
        deck_yml.read_text(encoding="utf8").replace("name: ABC", "name: XYZ"),
        encoding="utf8",
    )
    path = _links_file(
        repo,
        {
            "company/abc/pdf/abc-handout.pdf": "file-id-0001",
            "company/xyz/pdf/xyz-handout.pdf": "file-id-0002",
        },
    )
    # From the repository's root, not a deck.
    monkeypatch.chdir(repo)

    found = _json(
        capsys, "upload", "--reserve", "--dry-run", "--json", "--links", str(path)
    )

    assert found["link"] == {
        "company/abc/pdf/abc-handout.pdf": "file-id-0001",
        "company/xyz/pdf/xyz-handout.pdf": "file-id-0002",
    }
    assert "company/abc/pdf/abc-print-handout.pdf" in found["reserve"]
    assert "company/xyz/pdf/xyz-print-handout.pdf" in found["reserve"]

    # A deck's own refusals still apply.
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    drive_links.save(
        settings, {settings.paths.pdf_dir / "abc-handout.pdf": "other-id-01"}
    )
    with raises(SystemExit):
        main(("upload", "--reserve", "--dry-run", "--links", str(path)))


def test_links_file_and_link_dont_mix(repo: Path, caplog: Any) -> None:
    path = _links_file(repo, {"company/abc/pdf/abc-handout.pdf": "file-id-0001"})
    with raises(SystemExit):
        main(
            (
                "upload",
                "--reserve",
                "--links",
                str(path),
                "--link",
                "pdf/abc-handout.pdf=file-id-0002",
            )
        )
    assert "not both" in caplog.text


def test_reserve_with_a_links_file_adopts_every_file_at_once(
    repo: Path, capsys: CaptureFixture[str], monkeypatch: Any
) -> None:
    from deckz.extras import uploading

    xyz = repo / "company" / "xyz"
    copytree(_deck_dir(repo), xyz)
    deck_yml = xyz / "deck.yml"
    deck_yml.write_text(
        deck_yml.read_text(encoding="utf8").replace("name: ABC", "name: XYZ"),
        encoding="utf8",
    )
    path = _links_file(
        repo,
        {
            "company/abc/pdf/abc-handout.pdf": "file-id-0001",
            "company/xyz/pdf/xyz-handout.pdf": "file-id-0002",
        },
    )
    adopted: list[dict[Path, str]] = []

    class FakeUploader:
        def __init__(self, settings: DeckSettings) -> None:
            self.settings = settings

        def reserve(self, pdfs: list[Path], ids: dict[Path, str]) -> dict[Path, str]:
            return ids | {pdf: f"new-{pdf.name}" for pdf in pdfs if pdf not in ids}

    monkeypatch.setattr(uploading, "Uploader", FakeUploader)
    monkeypatch.setattr(
        uploading,
        "adopt",
        lambda _, ids, aliases=None: adopted.append(dict(ids)) or dict(ids),
    )
    monkeypatch.chdir(repo)

    main(("upload", "--reserve", "--links", str(path)))

    # One Picker for both decks.
    assert adopted == [
        {
            _deck_dir(repo) / "pdf" / "abc-handout.pdf": "file-id-0001",
            xyz / "pdf" / "xyz-handout.pdf": "file-id-0002",
        }
    ]
    for deck, name, file_id in (
        (_deck_dir(repo), "abc", "file-id-0001"),
        (xyz, "xyz", "file-id-0002"),
    ):
        settings = DeckSettings.from_yaml(deck)
        registry = drive_links.load(settings)
        assert registry[settings.paths.pdf_dir / f"{name}-handout.pdf"] == file_id
        printed = settings.paths.pdf_dir / f"{name}-print-handout.pdf"
        assert registry[printed] == f"new-{name}-print-handout.pdf"
    assert "2 of them existing files" in capsys.readouterr().out

    # Again: nothing left to do, no Picker.
    main(("upload", "--reserve", "--links", str(path)))
    assert len(adopted) == 1


def test_aliases_round_trip_apart_from_the_links(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    handout = settings.paths.pdf_dir / "abc-handout.pdf"
    drive_links.save(settings, {handout: "file-id"}, {handout: ["old-1", "old-2"]})

    assert drive_links.load(settings) == {handout: "file-id"}
    assert drive_links.load_aliases(settings) == {handout: ["old-1", "old-2"]}
    text = settings.paths.drive_links.read_text(encoding="utf8")
    assert "aliases:\n  pdf/abc-handout.pdf:\n  - old-1\n" in text

    # Saving the links alone keeps the aliases.
    printed = settings.paths.pdf_dir / "abc-print-handout.pdf"
    drive_links.save(settings, {handout: "file-id", printed: "print-id"})
    assert drive_links.load_aliases(settings) == {handout: ["old-1", "old-2"]}

    settings.paths.drive_links.write_text("aliases:\n  a: b\n", encoding="utf8")
    with raises(InvalidConfigurationError, match="aliases"):
        drive_links.load_aliases(settings)


def test_alias_requests_refuse_a_file_another_pdf_has(repo: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(repo))
    handout = settings.paths.pdf_dir / "abc-handout.pdf"
    printed = settings.paths.pdf_dir / "abc-print-handout.pdf"
    pdfs = [handout, printed]
    reserved = {handout: "own-file-01", printed: "print-file-01"}
    drive_links.save(settings, reserved, {printed: ["old-print-01"]})

    def requests(*given: str) -> dict[Path, list[str]]:
        return drive_links.alias_requests(settings, pdfs, given, reserved)

    link = "https://drive.google.com/file/d/old-handout-1/view"
    assert requests(
        f"pdf/abc-handout.pdf={link}",
        "company/abc/pdf/abc-handout.pdf=old-handout-2",
        # Known already: nothing to add.
        "pdf/abc-print-handout.pdf=old-print-01",
    ) == {handout: ["old-handout-1", "old-handout-2"]}
    for given, problem in (
        ("pdf/abc-handout.pdf", "give `<pdf>=<Drive link>`"),
        ("pdf/en/abc-handout.pdf=old-handout-1", "the deck builds no"),
        ("pdf/abc-handout.pdf=print-file-01", "itself, not an alias"),
        ("pdf/abc-handout.pdf=old-print-01", "is an alias of"),
    ):
        with raises(DeckzError, match=problem):
            requests(given)


def test_aliases_file_groups_the_aliases_by_deck(repo: Path) -> None:
    path = repo.parent / "links.yml"
    path.write_text(
        "company/abc/pdf/abc-handout.pdf: file-id-0001\n"
        "aliases:\n"
        "  company/abc/pdf/abc-handout.pdf:\n"
        "  - old-id-0001\n"
        "  - old-id-0002\n"
        "  company/abc/pdf/abc-print-handout.pdf: old-id-0003\n",
        encoding="utf8",
    )

    assert drive_links.links_file(path, repo) == {
        _deck_dir(repo): ["company/abc/pdf/abc-handout.pdf=file-id-0001"]
    }
    assert drive_links.aliases_file(path, repo) == {
        _deck_dir(repo): [
            "company/abc/pdf/abc-handout.pdf=old-id-0001",
            "company/abc/pdf/abc-handout.pdf=old-id-0002",
            "company/abc/pdf/abc-print-handout.pdf=old-id-0003",
        ]
    }
    path.write_text("aliases:\n  - a\n", encoding="utf8")
    with raises(DeckzError, match="`aliases:` section"):
        drive_links.aliases_file(path, repo)


def test_reserve_records_aliases_of_reserved_pdfs(
    repo: Path, capsys: CaptureFixture[str], monkeypatch: Any
) -> None:
    from deckz.extras import uploading

    settings = DeckSettings.from_yaml(_deck_dir(repo))
    handout = settings.paths.pdf_dir / "abc-handout.pdf"
    found = _json(
        capsys,
        "upload",
        "--reserve",
        "--dry-run",
        "--json",
        "--alias",
        "pdf/abc-handout.pdf=old-id-0001",
    )
    assert found["alias"] == {"company/abc/pdf/abc-handout.pdf": ["old-id-0001"]}

    # Every PDF reserved already: the aliases are still added.
    pdfs = {
        pdf: f"id-{pdf.name}"
        for pdf in published_pdfs(published_targets(settings, ("fr",)))
    }
    drive_links.save(settings, pdfs)
    adopted: list[dict[Path, list[str]]] = []
    monkeypatch.setattr(
        uploading,
        "adopt",
        lambda _, ids, aliases=None: adopted.append(dict(aliases or {})) or dict(ids),
    )

    main(("upload", "--reserve", "--alias", "pdf/abc-handout.pdf=old-id-0001"))

    assert adopted == [{handout: ["old-id-0001"]}]
    assert drive_links.load(settings) == pdfs
    assert drive_links.load_aliases(settings) == {handout: ["old-id-0001"]}
    assert "Added 1 aliases" in capsys.readouterr().out

    main(("upload", "--reserve", "--alias", "pdf/abc-handout.pdf=old-id-0001"))
    assert len(adopted) == 1
