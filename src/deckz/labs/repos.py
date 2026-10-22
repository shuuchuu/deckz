"""The labs with a repository of their own (`labs.repos`), and how they drift.

Such a lab's hands-on notebooks are its Colab version, and the repository's
README, on the branch a trainee opens in their language (`start`), the same
statement for a GitHub Codespace or a local clone. No check of the content
repository sees the other one, so `deckz labs repos` fetches each into a bare
mirror, under the content repository's git directory (shared by its
worktrees), and reports:

- a declared branch missing, or one the declaration lacks;
- a branch behind the one it stacks on (it lacks some of its commits);
- a README that doesn't give the statement yet (`statement: false`);
- a lab with no hands-on notebook in a start branch's language;
- a README whose Colab links name no notebook's ID, or not its own
  notebook's;

and, as notes, a README last changed before its notebook was, with the
notebook's commits since, to port or not.

Git runs as a subprocess, as in `deckz.labs.publishing`.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import DeckzError

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings, LabRepoSettings

_COLAB_LINK = re.compile(
    r"colab\.research\.google\.com/github/[^/\s)]+/[^/\s)]+/blob/[^/\s)]+/"
    r"([^/\s)]+)\.ipynb"
)
_README = "README.md"
_HANDS_ON = "hands-on"


class LabRepoFetchError(DeckzError):
    """A lab's repository couldn't be fetched."""


@dataclass(frozen=True)
class RepoReport:
    """What `deckz labs repos` found in one lab's repository."""

    repo: "LabRepoSettings"
    problems: list[str] = field(default_factory=list)
    """What to fix: a branch, a README, a missing notebook."""
    notes: list[str] = field(default_factory=list)
    """What to look at: a README older than its notebook."""


def _git(git_dir: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=git_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        msg = f"git {' '.join(args)} failed in {git_dir}: {result.stderr.strip()}"
        raise LabRepoFetchError(msg)
    return result.stdout.strip() if result.returncode == 0 else ""


def mirrors_dir(git_dir: Path) -> Path:
    """Where the mirrors of the lab repositories are.

    Returns:
        `deckz/lab-repos` in the repository's common git directory.
    """
    common = Path(_git(git_dir, "rev-parse", "--git-common-dir"))
    return (git_dir / common).resolve() / "deckz" / "lab-repos"


def mirror(git_dir: Path, repo: "LabRepoSettings", *, fetch: bool = True) -> Path:
    """The bare mirror of a lab's repository, fetched unless `fetch` is False.

    Returns:
        Its path.

    Raises:
        LabRepoFetchError: If it can't be fetched, or was never fetched and
            `fetch` is False.
    """
    path = mirrors_dir(git_dir) / f"{repo.repo}.git"
    if not path.is_dir():
        if not fetch:
            msg = f"{repo.repo} was never fetched: run without --no-fetch"
            raise LabRepoFetchError(msg)
        path.mkdir(parents=True)
        _git(path, "init", "--bare", "--quiet")
    if fetch:
        _git(
            path,
            "fetch",
            "--quiet",
            "--prune",
            repo.fetch_url,
            "+refs/heads/*:refs/heads/*",
        )
    return path


def _branches(path: Path) -> set[str]:
    out = _git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return set(out.splitlines())


def _branch_problems(path: Path, repo: "LabRepoSettings") -> list[str]:
    present = _branches(path)
    problems = [
        f"{branch}: missing" for branch in repo.branches if branch not in present
    ]
    problems += [
        f"{branch}: not in its declared branches: declare it, with the branch "
        "it stacks on, or delete it"
        for branch in sorted(present - set(repo.branches))
    ]
    for branch, base in repo.branches.items():
        if base is None or not {branch, base} <= present:
            continue
        behind = int(_git(path, "rev-list", "--count", f"{branch}..{base}"))
        if behind:
            problems.append(
                f"{branch}: lacks {behind} commit(s) of {base}: rebase it onto {base}"
            )
    return problems


def _notebook_id(path: Path, key: str) -> str | None:
    value = json.loads(path.read_text(encoding="utf-8")).get("metadata", {})
    for part in key.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, str) and value else None


def _notebook_ids(notebooks_dir: Path, key: str) -> set[str]:
    ids = (_notebook_id(path, key) for path in notebooks_dir.rglob("*.ipynb"))
    return {lab_id for lab_id in ids if lab_id}


def _day(timestamp: str) -> str:
    return datetime.fromtimestamp(int(timestamp), UTC).date().isoformat()


def _readme_problems(
    settings: "GlobalSettings",
    path: Path,
    repo: "LabRepoSettings",
    ids: set[str],
) -> tuple[list[str], list[str]]:
    git_dir = settings.paths.git_dir
    key = settings.labs.id_metadata_key
    present = _branches(path)
    problems: list[str] = []
    notes: list[str] = []
    for lang, branch in repo.start.items():
        notebook = (
            settings.paths.labs_notebooks_dir / repo.lab / f"{_HANDS_ON}-{lang}.ipynb"
        )
        where = notebook.relative_to(git_dir)
        own_id = _notebook_id(notebook, key) if notebook.is_file() else None
        if not notebook.is_file():
            problems.append(f"no {where}: the lab's Colab version in {lang}")
        if branch not in present:
            continue
        readme = _git(path, "show", f"{branch}:{_README}", check=False)
        if not readme:
            problems.append(f"{branch}: no {_README}")
            continue
        linked = set(_COLAB_LINK.findall(readme))
        problems += [
            f"{branch}'s {_README} links Colab notebook {lab_id}, an ID no notebook has"
            for lab_id in sorted(linked - ids)
        ]
        if own_id and own_id not in linked:
            problems.append(
                f"{branch}'s {_README} doesn't link its Colab version, {own_id}"
            )
        if not (repo.statement and notebook.is_file()):
            continue
        readme_date = _git(path, "log", "-1", "--format=%at", branch, "--", _README)
        since = _git(
            git_dir,
            "log",
            "--format=%h %as %s",
            f"--since=@{int(readme_date) + 1}",
            "--",
            str(where),
        ).splitlines()
        if since:
            notes.append(
                f"{branch}'s {_README} ({_day(readme_date)}) is older than "
                f"{where}'s last commits, to port or not:\n"
                + "\n".join(f"  {line}" for line in since)
            )
    return problems, notes


def report(
    settings: "GlobalSettings", repo: "LabRepoSettings", *, fetch: bool = True
) -> RepoReport:
    """Where a lab's repository drifts from its declaration and its notebooks.

    Returns:
        Its problems and notes.
    """
    path = mirror(settings.paths.git_dir, repo, fetch=fetch)
    ids = _notebook_ids(
        settings.paths.labs_notebooks_dir, settings.labs.id_metadata_key
    )
    problems = _branch_problems(path, repo)
    if not repo.statement:
        problems.append(
            "its READMEs don't give the lab's statement yet (statement: false)"
        )
    readme_problems, notes = _readme_problems(settings, path, repo, ids)
    return RepoReport(repo, problems + readme_problems, notes)
