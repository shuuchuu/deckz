import subprocess
from pathlib import Path
from shutil import copytree
from typing import Any

from pytest import fixture

from deckz.cli import main
from deckz.configuring.settings import GlobalSettings
from deckz.status import changed_paths, decks_section, status, translation_section


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


def test_status_command_prints_every_section(repo: Path, capsys: Any) -> None:
    main(("status", "--no-checks"))

    output = capsys.readouterr().out
    assert output.startswith("Your changes: 0 changed files")
    for title in ("Translation", "Labs", "Videos", "Built decks"):
        assert f" {title}: " in output
