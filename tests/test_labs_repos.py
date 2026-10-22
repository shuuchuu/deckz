import json
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pytest import raises

from deckz.cli import main
from deckz.configuring.settings import (
    GlobalPaths,
    GlobalSettings,
    LabRepoSettings,
    LabsSettings,
)
from deckz.labs.repos import LabRepoFetchError, mirrors_dir, report

LAB = "topic/lab"
COLAB = "https://colab.research.google.com/github/acme/labs/blob/main"


def _git(cwd: Path, *args: str, date: str | None = None) -> str:
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=test",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    ).stdout


def _commit(
    repo: Path, files: dict[str, str], message: str, date: str | None = None
) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", *files)
    _git(repo, "commit", "--quiet", "-m", message, date=date)


def _notebook(lab_id: str) -> str:
    return json.dumps({"cells": [], "metadata": {"shuuchuu": {"id": lab_id}}})


def _lab_repo(tmp_path: Path) -> Path:
    # A lab repository in the four-branch shape, its READMEs linking their
    # notebooks.
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "--quiet", "-b", "main")
    _commit(upstream, {"README.md": f"[Colab]({COLAB}/lab-fr.ipynb)\n"}, "Start")
    _git(upstream, "switch", "--quiet", "-c", "main-en")
    _commit(upstream, {"README.md": f"[Colab]({COLAB}/lab-en.ipynb)\n"}, "Translate")
    _git(upstream, "switch", "--quiet", "-c", "solution", "main")
    _commit(upstream, {"solution.py": "x = 1\n"}, "Solve")
    _git(upstream, "switch", "--quiet", "-c", "solution-en", "solution")
    _git(upstream, "cherry-pick", "main..main-en")
    _git(upstream, "switch", "--quiet", "main")
    return upstream


def _content_repo(tmp_path: Path) -> Path:
    git_dir = tmp_path / "content"
    git_dir.mkdir()
    _git(git_dir, "init", "--quiet", "-b", "main")
    _commit(
        git_dir,
        {
            f"labs/notebooks/{LAB}/hands-on-fr.ipynb": _notebook("lab-fr"),
            f"labs/notebooks/{LAB}/hands-on-en.ipynb": _notebook("lab-en"),
        },
        "Add the lab",
        "2010-01-01T00:00:00",
    )
    return git_dir


def _settings(git_dir: Path, repo: LabRepoSettings) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        labs=LabsSettings(repos=(repo,)),
    )


def _report(tmp_path: Path, **fields: object) -> tuple[list[str], list[str]]:
    upstream = _lab_repo(tmp_path)
    git_dir = _content_repo(tmp_path)
    repo = LabRepoSettings.model_validate(
        {"repo": "acme/lab", "lab": LAB, "url": str(upstream), **fields}
    )
    found = report(_settings(git_dir, repo), repo)
    return found.problems, found.notes


def test_report_passes_a_repository_in_step(tmp_path: Path) -> None:
    assert _report(tmp_path) == ([], [])


def test_report_fetches_into_the_common_git_dir(tmp_path: Path) -> None:
    _report(tmp_path)

    mirror = mirrors_dir(tmp_path / "content") / "acme" / "lab.git"
    assert (
        mirror
        == tmp_path / "content" / ".git" / "deckz" / "lab-repos" / "acme" / "lab.git"
    )
    assert "solution-en" in _git(mirror, "branch")


def test_report_flags_a_branch_behind_its_base(tmp_path: Path) -> None:
    upstream = _lab_repo(tmp_path)
    _commit(upstream, {"pyproject.toml": "\n"}, "Update the template")
    git_dir = _content_repo(tmp_path)
    repo = LabRepoSettings(repo="acme/lab", lab=LAB, url=str(upstream))

    problems = report(_settings(git_dir, repo), repo).problems

    assert problems == [
        "main-en: lacks 1 commit(s) of main: rebase it onto main",
        "solution: lacks 1 commit(s) of main: rebase it onto main",
    ]


def test_report_flags_missing_and_undeclared_branches(tmp_path: Path) -> None:
    problems, _ = _report(
        tmp_path,
        branches={"main": None, "main-en": "main", "gui": "main", "solution": "main"},
    )

    assert problems == [
        "gui: missing",
        "solution-en: not in its declared branches: declare it, with the branch "
        "it stacks on, or delete it",
    ]


def test_report_flags_readme_links(tmp_path: Path) -> None:
    upstream = _lab_repo(tmp_path)
    _git(upstream, "switch", "--quiet", "main-en")
    _commit(upstream, {"README.md": f"[Colab]({COLAB}/gone.ipynb)\n"}, "Relink")
    git_dir = _content_repo(tmp_path)
    repo = LabRepoSettings(repo="acme/lab", lab=LAB, url=str(upstream))

    problems = report(_settings(git_dir, repo), repo).problems

    assert "main-en's README.md links Colab notebook gone, an ID no notebook has" in (
        problems
    )
    assert "main-en's README.md doesn't link its Colab version, lab-en" in problems


def test_report_flags_a_missing_notebook_and_statement(tmp_path: Path) -> None:
    problems, _ = _report(tmp_path, lab="topic/other", statement=False)

    assert problems == [
        "its READMEs don't give the lab's statement yet (statement: false)",
        "no labs/notebooks/topic/other/hands-on-fr.ipynb: the lab's Colab version "
        "in fr",
        "no labs/notebooks/topic/other/hands-on-en.ipynb: the lab's Colab version "
        "in en",
    ]


def test_report_notes_a_readme_older_than_its_notebook(tmp_path: Path) -> None:
    upstream = _lab_repo(tmp_path)
    git_dir = _content_repo(tmp_path)
    _git(upstream, "commit", "--quiet", "--amend", "--no-edit", "--date=2000-01-01")
    repo = LabRepoSettings(repo="acme/lab", lab=LAB, url=str(upstream))

    notes = report(_settings(git_dir, repo), repo).notes

    assert len(notes) == 1
    assert notes[0].startswith("main's README.md (2000-01-01) is older than")
    assert notes[0].endswith("2010-01-01 Add the lab")


def test_report_without_fetch_needs_a_mirror(tmp_path: Path) -> None:
    git_dir = _content_repo(tmp_path)
    repo = LabRepoSettings(repo="acme/lab", lab=LAB, url=str(tmp_path / "nowhere"))

    with raises(LabRepoFetchError, match="never fetched"):
        report(_settings(git_dir, repo), repo, fetch=False)


def test_settings_refuse_an_unknown_start_branch() -> None:
    with raises(ValidationError, match="main-en not in its branches"):
        LabRepoSettings(repo="acme/lab", lab=LAB, branches={"main": None})


def test_settings_refuse_an_unknown_base_branch() -> None:
    repo = LabRepoSettings(
        repo="acme/lab", lab=LAB, branches={"main": None, "main-en": "dev"}
    )

    with raises(ValidationError, match="dev not in its branches"):
        LabsSettings(repos=(repo,))


def _gui_lab(**fields: object) -> LabRepoSettings:
    # A second starting point of the same repository, on its solution.
    return LabRepoSettings.model_validate(
        {
            "repo": "acme/lab",
            "lab": "topic/gui",
            "branches": {"gui": "solution", "gui-en": "gui"},
            "start": {"fr": "gui", "en": "gui-en"},
            **fields,
        }
    )


def test_settings_accept_labs_sharing_a_repository() -> None:
    labs = LabsSettings(repos=(LabRepoSettings(repo="acme/lab", lab=LAB), _gui_lab()))

    assert labs.repo_branches("acme/lab")["gui"] == "solution"


def test_report_merges_the_branches_of_labs_sharing_a_repository(
    tmp_path: Path,
) -> None:
    upstream = _lab_repo(tmp_path)
    _git(upstream, "switch", "--quiet", "-c", "gui", "solution")
    _commit(upstream, {"README.md": "GUI\n"}, "Start the GUI")
    _git(upstream, "switch", "--quiet", "-c", "gui-en", "gui")
    _commit(upstream, {"README.md": "GUI, in English\n"}, "Translate")
    git_dir = _content_repo(tmp_path)
    cli = LabRepoSettings(repo="acme/lab", lab=LAB, url=str(upstream))
    gui = _gui_lab(url=str(upstream), colab=False)
    settings = GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        labs=LabsSettings(repos=(cli, gui)),
    )

    assert report(settings, cli).problems == []
    assert report(settings, gui, fetch=False).problems == []


def test_settings_refuse_two_repositories_for_a_lab() -> None:
    repo = LabRepoSettings(repo="acme/lab", lab=LAB)

    with raises(ValidationError, match="several repositories"):
        LabsSettings(repos=(repo, repo.model_copy(update={"repo": "acme/other"})))


def test_repos_command_reports_and_exits_1_on_a_problem(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    upstream = _lab_repo(tmp_path)
    _commit(upstream, {"pyproject.toml": "\n"}, "Update the template")
    git_dir = _content_repo(tmp_path)
    (git_dir / "deckz.yml").write_text(
        f"labs:\n  repos:\n    - repo: acme/lab\n      lab: {LAB}\n"
        f"      url: {upstream}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(git_dir)

    with raises(SystemExit) as exited:
        main(("labs", "repos", "lab"))

    assert exited.value.code == 1
    assert capsys.readouterr().out.startswith(
        f"acme/lab ({LAB})\n  main-en: lacks 1 commit(s) of main"
    )


def test_repos_command_refuses_an_unknown_name(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.chdir(_content_repo(tmp_path))

    with raises(SystemExit) as exited:
        main(("labs", "repos", "nothing"))

    assert exited.value.code == 2
    assert capsys.readouterr().out == "not in labs.repos: nothing\n"
