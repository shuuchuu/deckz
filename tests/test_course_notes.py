import json
from pathlib import Path
from shutil import copytree
from typing import Any

import appdirs
from pygit2 import init_repository
from pypdfium2 import PdfDocument
from pytest import CaptureFixture, fixture, raises

from deckz.analyzing.content_checks import course_notes_files, course_notes_pairs
from deckz.analyzing.i18n_stale import lang_pairs
from deckz.cli import main
from deckz.configuring.settings import (
    CourseNotesSettings,
    DeckSettings,
    GlobalPaths,
    GlobalSettings,
)
from deckz.course_notes import ChapterStatus, chapters_deck, entries
from deckz.models import File, PartName

# The template's own text, so a test tells it from main.typ's output.
_TEMPLATE = """= Course notes of {{ variables.lang }}
{% for part in parts %}
{% for section in part.sections %}
{% if section is string %}
#include "{{ section }}.typ"
{% else %}
== {{ section.title }}
{% endif %}
{% endfor %}
{% endfor %}
"""


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / "test_cli_typst"
    repo = tmp_path / "data"
    copytree(data_dir, repo)
    init_repository(str(repo))
    (repo / "templates" / "jinja2" / "course-notes.typ").write_text(
        _TEMPLATE, encoding="utf8"
    )
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.chdir(repo / "company" / "abc")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(user_dir))
    return repo


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def _chapter(repo: Path, path: str, text: str) -> None:
    _write(repo / "course-notes" / f"{path}.md", text)


def _pdf_text(path: Path) -> str:
    pdf = PdfDocument(path)
    try:
        return "\n".join(page.get_textpage().get_text_bounded() for page in pdf)
    finally:
        pdf.close()


def _settings(repo: Path, **course_notes: Any) -> DeckSettings:
    settings = DeckSettings.from_yaml(repo / "company" / "abc")
    return settings.model_copy(
        update={"course_notes": CourseNotesSettings(**course_notes)}
    )


def _deck(settings: DeckSettings) -> Any:
    from deckz.components.factory import DeckSettingsFactory

    return (
        DeckSettingsFactory(settings)
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )


def test_run_course_notes_compiles_the_chapters(repo: Path) -> None:
    _chapter(
        repo, "greeting/hello", "# Hello, at length\n\nThe written-out greeting.\n"
    )

    main(("run", "course-notes"))

    pdf = repo / "company" / "abc" / "pdf" / "course-notes" / "abc-course-notes.pdf"
    text = _pdf_text(pdf)
    assert "Course notes of fr" in text
    assert "The written-out greeting." in text
    assert "Greeting" in text  # the section's title
    assert "Hi there" not in text  # the slides' own text
    assert "the answer is" not in text  # about.md has no chapter
    # The deck's own PDFs are a separate build.
    assert not list((repo / "company" / "abc" / "pdf").glob("*.pdf"))


def test_run_course_notes_in_english_reads_en_chapters(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Bonjour\n\nLe salut rédigé.\n")
    _chapter(repo, "greeting/en/hello", "# Hello\n\nThe written-out greeting.\n")
    (repo / "content" / "greeting" / "en").mkdir()
    (repo / "content" / "greeting" / "en" / "hello.md").write_text("# Hello\n")
    (repo / "company" / "abc" / "content" / "en").mkdir()
    (repo / "company" / "abc" / "content" / "en" / "about.md").write_text("# About\n")

    main(("run", "course-notes", "--lang", "en"))

    pdf = repo / "company" / "abc" / "pdf" / "course-notes" / "en"
    text = _pdf_text(pdf / "abc-course-notes.pdf")
    assert "The written-out greeting." in text
    assert "Course notes of en" in text


def test_run_course_notes_without_any_chapter_fails(repo: Path, caplog: Any) -> None:
    with raises(SystemExit) as error:
        main(("run", "course-notes"))

    assert error.value.code == 1
    assert "no course notes chapter in fr yet" in caplog.text


def test_run_course_notes_dry_run(repo: Path, capsys: CaptureFixture[str]) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")

    main(("run", "course-notes", "--dry-run"))

    out = capsys.readouterr().out
    assert "company/abc/pdf/course-notes/abc-course-notes.pdf: render all 1" in out
    assert not (repo / "company" / "abc" / "pdf").exists()


def test_course_notes_suffix_names_the_pdf(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")
    (repo / "deckz.yml").write_text(
        (repo / "deckz.yml").read_text() + "course_notes:\n  suffix: support\n"
    )

    main(("run", "course-notes"))

    pdf = repo / "company" / "abc" / "pdf" / "course-notes" / "abc-support.pdf"
    assert pdf.is_file()


def test_show_course_notes_lists_each_file_s_chapter(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")

    main(("show", "course-notes", "--json"))

    found = {e["path"]: e for e in json.loads(capsys.readouterr().out)}
    assert found["about"]["status"] == "missing"
    assert found["greeting/hello"]["status"] == "written"
    assert found["greeting/hello"]["chapter"] == "course-notes/greeting/hello.md"


def test_entries_skip_and_same_as(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")

    skipping = _settings(repo, skip=("abo*",))
    statuses = {e.path: e.status for e in entries(skipping, _deck(skipping), "fr")}
    assert statuses == {
        "about": ChapterStatus.SKIPPED,
        "greeting/hello": ChapterStatus.WRITTEN,
    }

    covering = _settings(repo, same_as={"about": "greeting/hello"})
    statuses = {e.path: e.status for e in entries(covering, _deck(covering), "fr")}
    assert statuses["about"] is ChapterStatus.COVERED


def test_chapters_deck_includes_a_shared_chapter_once(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")
    settings = _settings(repo, same_as={"about": "greeting/hello"})

    deck = chapters_deck(settings, _deck(settings), "fr")

    part = deck.parts[PartName("p1")]
    # `about` comes first and brings the chapter; the section, left empty, goes.
    assert len(part.nodes) == 1
    file = part.nodes[0]
    assert isinstance(file, File)
    assert str(file.unresolved_path) == "greeting/hello"
    assert file.resolved_path == (repo / "course-notes/greeting/hello.md").resolve()


def _global(git_dir: Path, **course_notes: Any) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        course_notes=CourseNotesSettings(**course_notes),
    )


def test_course_notes_files_flags_a_chapter_of_no_content_file(
    tmp_path: Path,
) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "content" / "topic" / "kept.md", "# Kept\n")
    _write(tmp_path / "course-notes" / "topic" / "kept.md", "# Kept\n")
    _write(tmp_path / "course-notes" / "topic" / "renamed.md", "# Renamed\n")
    _write(tmp_path / "course-notes" / "topic" / "en" / "renamed.md", "# Renamed\n")

    problems = course_notes_files(_global(tmp_path))

    assert len(problems) == 2
    assert all("no content/topic/renamed.md" in problem for problem in problems)


def test_course_notes_files_flags_same_as_conflicts(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "content" / "short.md", "# Short\n")
    _write(tmp_path / "content" / "full.md", "# Full\n")
    _write(tmp_path / "course-notes" / "short.md", "# Short\n")

    problems = course_notes_files(
        _global(tmp_path, same_as={"short": "full", "gone": "full"})
    )

    assert any("covers short: remove one of them" in p for p in problems)
    assert any("same_as gone: no content file gone" in p for p in problems)


def test_course_notes_pairs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "course-notes" / "a.md", "# A\n")
    _write(tmp_path / "course-notes" / "en" / "a.md", "# A\n")
    _write(tmp_path / "course-notes" / "fr-only.md", "# F\n")
    _write(tmp_path / "course-notes" / "en" / "en-only.md", "# E\n")

    problems = course_notes_pairs(_global(tmp_path))

    assert problems == [
        "course-notes/en/en-only.md: no French version (course-notes/en-only.md)",
        "course-notes/fr-only.md: no English version (course-notes/en/fr-only.md)",
    ]


def test_chapters_are_lang_sync_pairs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "course-notes" / "topic" / "a.md", "# A\n")

    pairs = lang_pairs(_global(tmp_path))

    assert [(str(fr), str(en)) for fr, en in pairs] == [
        ("course-notes/topic/a.md", "course-notes/topic/en/a.md")
    ]


def test_agent_notes_are_neither_chapters_nor_pairs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "content" / "topic" / "a.md", "# A\n")
    _write(tmp_path / "content" / "topic" / "en" / "a.md", "# A\n")
    for notes in ("content/CLAUDE.md", "content/topic/AGENTS.md"):
        _write(tmp_path / notes, "# Notes\n")
    _write(tmp_path / "course-notes" / "CLAUDE.md", "# Notes\n")

    assert course_notes_files(_global(tmp_path)) == []
    assert course_notes_pairs(_global(tmp_path)) == []
    assert [str(fr) for fr, _ in lang_pairs(_global(tmp_path))] == [
        "content/topic/a.md"
    ]


def test_no_course_notes_directory_means_no_problem(tmp_path: Path) -> None:
    init_repository(str(tmp_path))

    assert course_notes_files(_global(tmp_path)) == []
    assert course_notes_pairs(_global(tmp_path)) == []


_NOTES_PDF = Path("pdf") / "course-notes" / "abc-course-notes.pdf"
_HANDOUT_ONLY = ("--no-presentation", "--no-print", "--no-part-handouts")


def test_run_with_course_notes_builds_both(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n\nThe written-out greeting.\n")
    deck = repo / "company" / "abc"

    main(("run", *_HANDOUT_ONLY, "--course-notes"))

    assert "Hi there" in _pdf_text(deck / "pdf" / "abc-handout.pdf")
    assert "The written-out greeting." in _pdf_text(deck / _NOTES_PDF)
    # --sync (the default) keeps the deck's handout, and leaves the notes alone.
    assert sorted(p.name for p in (deck / "pdf").glob("*.pdf")) == ["abc-handout.pdf"]


def test_run_with_course_notes_but_no_chapter_builds_the_slides(
    repo: Path, caplog: Any
) -> None:
    deck = repo / "company" / "abc"

    main(("run", *_HANDOUT_ONLY, "--course-notes"))

    assert (deck / "pdf" / "abc-handout.pdf").is_file()
    assert not (deck / "pdf" / "course-notes").exists()
    assert "No course notes chapter yet" in caplog.text


def test_run_course_notes_only(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")
    deck = repo / "company" / "abc"

    main(("run", "--no-handout", "--no-presentation", "--no-print", "--course-notes"))

    assert (deck / _NOTES_PDF).is_file()
    assert not list((deck / "pdf").glob("*.pdf"))


def test_course_notes_default_from_the_environment(
    repo: Path, monkeypatch: Any, capsys: CaptureFixture[str]
) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")
    monkeypatch.setenv("DECKZ_RUN_COURSE_NOTES", "true")

    main(("run", *_HANDOUT_ONLY, "--dry-run"))

    out = capsys.readouterr().out
    assert "company/abc/pdf/abc-handout.pdf: render all" in out
    assert "company/abc/pdf/course-notes/abc-course-notes.pdf: render all 1" in out


def test_run_decks_with_course_notes(repo: Path) -> None:
    _chapter(repo, "greeting/hello", "# Hello\n")
    deck = repo / "company" / "abc"

    main(("run", "decks", "--handout", "--no-presentation", "--course-notes"))

    assert (deck / "pdf" / "abc-handout.pdf").is_file()
    assert (deck / _NOTES_PDF).is_file()
