import subprocess
from pathlib import Path
from shutil import copytree
from typing import Any

from pytest import fixture

from deckz.cli import main
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.stamps import digest, write_stamp
from deckz.status import (
    changed_paths,
    checks_section,
    course_notes_section,
    deck_status,
    decks_section,
    status,
    translation_section,
    videos_section,
)
from deckz.videos import renders, scenes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs

    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (root / "user-variables.yml").rename(user_dir / "variables.yml")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "Start")
    monkeypatch.chdir(root)
    return root


def _settings(repo: Path) -> GlobalSettings:
    return GlobalSettings.from_yaml(repo)


def test_changed_paths_are_the_working_tree_and_the_commits_since(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "content" / "questions.md").write_text("Changed\n", encoding="utf8")
    _git(repo, "commit", "--quiet", "-am", "Change questions")
    (repo / "new.md").write_text("New\n", encoding="utf8")
    _git(repo, "mv", "content/about/extra.md", "content/about/more.md")

    uncommitted, changed = changed_paths(repo, base)

    assert uncommitted == {"new.md", "content/about/more.md"}
    assert changed == uncommitted | {"content/questions.md"}


def test_translation_flags_an_uncommitted_one_sided_edit(repo: Path) -> None:
    hello = repo / "company" / "bilingual" / "content" / "hello.md"
    hello.write_text(hello.read_text() + "\nMore.\n", encoding="utf8")
    uncommitted, changed = changed_paths(repo, None)

    section = translation_section(_settings(repo), uncommitted, changed)

    assert [item.text for item in section.items] == [
        "company/bilingual/content/hello.md: changed without "
        "company/bilingual/content/en/hello.md (not committed yet)"
    ]


def _english_gaps(repo: Path) -> Path:
    # A new French file with no English version, and a title with no `en` key.
    deck = repo / "company" / "bilingual"
    (deck / "content" / "bye.md").write_text("# Au revoir\n", encoding="utf8")
    definition = deck / "deck.yml"
    definition.write_text(
        definition.read_text().replace("en: Part 1", "")
        + "      - bye:\n          fr: Au revoir\n          en: Bye\n",
        encoding="utf8",
    )
    return deck


def test_translation_lists_the_english_gaps_of_the_reached_decks(repo: Path) -> None:
    from deckz.analyzing.affected import affected_decks

    _english_gaps(repo)
    uncommitted, changed = changed_paths(repo, None)
    decks = affected_decks(repo, [Path(path) for path in changed])

    section = translation_section(_settings(repo), uncommitted, changed, decks)

    assert section.summary.startswith("2 gaps failing an English build; ")
    assert [(item.text, item.fix) for item in section.items] == [
        (
            "company/bilingual/content/bye.md: no English version "
            "company/bilingual/content/en/bye.md (the English build of "
            "company/bilingual fails)",
            "translate it into company/bilingual/content/en/bye.md",
        ),
        (
            "company/bilingual/deck.yml: parts[p1].title has no `en` translation "
            "(the English build of company/bilingual fails)",
            "add `en:` to parts[p1].title in company/bilingual/deck.yml",
        ),
    ]


def test_deck_status_counts_the_english_gaps(repo: Path) -> None:
    deck = _english_gaps(repo)

    _, sections = deck_status(DeckSettings.from_yaml(deck), checks=False, decks=False)

    translation = next(s for s in sections if s.key == "translation")
    assert translation.summary == "2 gaps failing its English build"
    assert len(translation.items) == 2


def test_decks_flags_the_reached_decks_outdated_pdfs(repo: Path) -> None:
    deck = repo / "company" / "bilingual"
    main(
        ("run", "--workdir", str(deck), "--handout", "--no-presentation", "--no-print")
    )
    hello = deck / "content" / "hello.md"
    hello.write_text(hello.read_text() + "\nMore.\n", encoding="utf8")

    section = decks_section(_settings(repo), {"company/bilingual/content/hello.md"})

    assert section.summary == "your changes reach 1 deck: company/bilingual"
    assert [item.text for item in section.items] == [
        "company/bilingual: 2 PDFs not matching its content"
    ]


def test_status_without_labs_nor_videos(repo: Path) -> None:
    scope, sections = status(_settings(repo), checks=False)

    assert scope == "0 changed files, the working tree only (no upstream branch)"
    summaries = {section.title: section.summary for section in sections}
    assert summaries["Labs"] == "no lab notebooks"
    assert summaries["Videos"] == "no videos"
    assert summaries["Built decks"] == "your changes reach no deck"
    # Programs tell the sections apart by key, whatever their titles.
    assert [section.key for section in sections] == [
        "translation",
        "labs",
        "videos",
        "decks",
    ]
    _, sections = status(_settings(repo), checks=False, decks=False)
    assert [section.key for section in sections] == ["translation", "labs", "videos"]


def _scene(repo: Path) -> None:
    module = repo / "figures" / "scenes" / "nn" / "demo.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from deckz.videos import register_scene\n\n\n"
        "@register_scene\nclass Demo:\n    pass\n",
        encoding="utf8",
    )


def test_videos_names_each_draft(repo: Path, tmp_path: Path) -> None:
    _scene(repo)
    _git(repo, "remote", "add", "videos", str(tmp_path / "videos.git"))
    settings = _settings(repo)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]
    render.file.parent.mkdir(parents=True)
    render.file.write_bytes(b"video")
    render.file.with_suffix(".png").write_bytes(b"poster")
    render.file.with_suffix(".quality").write_text("l", encoding="utf8")
    write_stamp(render.file, digest(scene.sources()))

    section = videos_section(settings, fetch=False)

    assert [(item.text, item.fix) for item in section.items] == [
        (
            "assets/videos/nn/demo.mp4 is a draft (l), not at the published "
            "quality (h)",
            "`deckz videos render nn/demo` renders it at the published quality",
        )
    ]


def test_videos_names_a_missing_remote_and_how_to_add_it(repo: Path) -> None:
    _scene(repo)
    (repo / "deckz.yml").write_text(
        (repo / "deckz.yml").read_text(encoding="utf8")
        + "setup:\n  remotes:\n    videos: git@example.com:owner/videos.git\n",
        encoding="utf8",
    )

    section = videos_section(_settings(repo), fetch=True)

    assert section.summary == "not compared with the published ones"
    assert (
        "no `videos` remote in this clone, to publish to",
        "`deckz setup` adds it "
        "(`git remote add videos git@example.com:owner/videos.git`)",
    ) in [(item.text, item.fix) for item in section.items]


def test_status_command_prints_every_section(repo: Path, capsys: Any) -> None:
    main(("status", "--no-checks"))

    output = capsys.readouterr().out
    assert output.startswith("Your changes: 0 changed files")
    for title in ("Translation", "Labs", "Videos", "Built decks"):
        assert f" {title}: " in output


def test_checks_name_the_problems_of_your_changes_first(repo: Path) -> None:
    # Old problems, many of them, committed.
    for i in range(20):
        (repo / "content" / f"old-{i:02}.tex").write_text("x\n", encoding="utf8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "Old problems")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "content" / "questions.md").write_text("{{ broken\n", encoding="utf8")
    _, changed = changed_paths(repo, base)

    section = checks_section(_settings(repo), changed)

    assert section.summary == (
        "21 problems, 1 blocking a commit: `deckz check` lists them"
    )
    assert section.items[0].text.startswith("jinja-syntax: content/questions.md:1:")
    assert section.items[0].blocks_commit
    assert section.items[1].text.startswith("raw-latex: content/old-00.tex")
    assert not section.items[1].blocks_commit
    assert section.items[-1].text == "... and 6 more"


def _chapter(repo: Path, path: str) -> None:
    chapter = repo / "course-notes" / f"{path}.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# Chapter\n", encoding="utf8")


def test_deck_status_lists_the_files_missing_a_chapter(repo: Path) -> None:
    # abc has 4 content files: 3 chapters in French, 2 in English.
    for path in ("intro", "advanced", "conclusion", "en/intro", "en/advanced"):
        _chapter(repo, f"first-section/{path}")

    _, sections = deck_status(
        DeckSettings.from_yaml(repo / "company" / "abc"), checks=False, decks=False
    )

    notes = next(s for s in sections if s.key == "course-notes")
    assert notes.summary == "3 chapters to write"
    assert [item.text for item in notes.items] == [
        "fr: about has no chapter (course-notes/about.md)",
        "en: first-section/conclusion has no chapter "
        "(course-notes/first-section/en/conclusion.md)",
        "en: about has no chapter (course-notes/en/about.md)",
    ]
    assert "course_notes" in notes.items[0].fix


def test_course_notes_flag_only_the_decks_that_have_some(repo: Path) -> None:
    decks = [
        DeckSettings.from_yaml(repo / "company" / name) for name in ("abc", "bilingual")
    ]
    # No course notes directory: no section.
    assert course_notes_section(_settings(repo), decks) is None
    # 1 of abc's 4 files with a chapter: abc has no course notes.
    _chapter(repo, "first-section/intro")
    section = course_notes_section(_settings(repo), decks)
    assert section is not None
    assert section.items == ()
    # 2 of 4 in French: the 2 others are missing; English has no course notes.
    _chapter(repo, "first-section/advanced")

    section = course_notes_section(_settings(repo), decks)

    assert section is not None
    assert section.summary == "1 deck with course notes chapters to write"
    assert [item.text for item in section.items] == [
        "company/abc: content files with no course notes chapter, 2 in fr"
    ]
    assert "--workdir company/abc --lang fr" in section.items[0].fix


def test_deck_status_without_course_notes_says_so(repo: Path) -> None:
    (repo / "course-notes").mkdir()

    _, sections = deck_status(
        DeckSettings.from_yaml(repo / "company" / "abc"), checks=False, decks=False
    )

    notes = next(s for s in sections if s.key == "course-notes")
    assert notes.summary.startswith("none: fewer than half")
    assert notes.items == ()
