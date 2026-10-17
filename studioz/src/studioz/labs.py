"""The workspace's lab notebooks: the TP view and a notebook's page.

What the workspace's own `deckz labs list --json` lists (under a second):
each notebook's lab (its directory under the notebooks' one), kind (`demo`,
`hands-on`) and language. A notebook is shown rendered (`studioz.notebooks`),
never edited here (it's JSON): the agent edits it, or the person in their own
editor (`open_in_editor`).
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any

from deckz.models import Lang

from .watches import workspace_environment

KINDS = {"hands-on": "TP", "demo": "démo"}
"""The kinds' names on screen; another kind shows as deckz names it."""

_TIMEOUT = 60


@dataclass(frozen=True)
class Notebook:
    lab: str
    """Its lab's directory, under the notebooks' one: `nlp/word-embeddings`."""
    kind: str
    language: str
    file: str
    """Relative to the workspace."""

    @property
    def name(self) -> str:
        """What a notebook's page is named by: `nlp/word-embeddings/demo`.

        Returns:
            Its lab and kind.
        """
        return f"{self.lab}/{self.kind}"


@dataclass(frozen=True)
class Lab:
    lab: str
    notebooks: tuple[Notebook, ...]

    def kinds(self) -> dict[str, tuple[Notebook, ...]]:
        """Its notebooks by kind, demo first.

        Returns:
            Each kind's notebooks, French first.
        """
        found: dict[str, list[Notebook]] = {}
        for notebook in self.notebooks:
            found.setdefault(notebook.kind, []).append(notebook)
        rank = {"demo": 0, "hands-on": 1}
        return {
            kind: tuple(found[kind])
            for kind in sorted(found, key=lambda kind: (rank.get(kind, 2), kind))
        }


@dataclass(frozen=True)
class Listing:
    notebooks_dir: str
    notebooks: tuple[Notebook, ...]
    error: str | None = None
    """Why deckz couldn't list them."""

    def find(self, name: str, lang: Lang) -> Notebook | None:
        """The notebook a page shows.

        Returns:
            The `lang` one of `name` (`<lab>/<kind>`), else its other one, \
            None if there's neither.
        """
        found = [n for n in self.notebooks if n.name == name]
        return next(
            (n for n in found if n.language == lang), found[0] if found else None
        )

    def languages(self, name: str) -> tuple[str, ...]:
        return tuple(n.language for n in self.notebooks if n.name == name)

    def folders(self) -> dict[str, list[Lab]]:
        """The labs by folder (`nlp` for `nlp/word-embeddings`).

        Returns:
            Each folder's labs, the folders by name (a folder's own labs \
            before its subfolders'), the labs in deckz's order.
        """
        labs: dict[str, list[Notebook]] = {}
        for notebook in self.notebooks:
            labs.setdefault(notebook.lab, []).append(notebook)
        found: dict[str, list[Lab]] = {}
        for lab, notebooks in labs.items():
            found.setdefault(lab.rpartition("/")[0], []).append(
                Lab(lab, tuple(notebooks))
            )
        return dict(sorted(found.items()))


# Each workspace's last listing, and the notebook files it was made from:
# the pages poll (a notebook edited in the person's own editor fires no
# event), and the listing changes only when a notebook is added or removed.
_LISTINGS: dict[Path, tuple[tuple[str, ...], "Listing"]] = {}


def _files(workspace: Path, notebooks_dir: str) -> tuple[str, ...]:
    root = workspace / notebooks_dir
    return tuple(sorted(str(p) for p in root.rglob("*.ipynb"))) if root.is_dir() else ()


def listing(workspace: Path) -> Listing:
    """The workspace's lab notebooks, as its own deckz lists them.

    Returns:
        Each notebook, in deckz's order, or why it failed; the last listing \
        while the notebook files are the same.
    """
    cached = _LISTINGS.get(workspace)
    if cached is not None:
        files = _files(workspace, cached[1].notebooks_dir)
        if files == cached[0]:
            return cached[1]
    found = _listing(workspace)
    if not found.error:
        # Taken after the listing: a notebook added meanwhile lists it again.
        _LISTINGS[workspace] = (_files(workspace, found.notebooks_dir), found)
    return found


def _listing(workspace: Path) -> Listing:
    try:
        result = subprocess.run(
            [str(workspace / ".venv" / "bin" / "deckz"), "labs", "list", "--json"],
            cwd=workspace,
            env=workspace_environment(workspace),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Listing("", (), str(error))
    try:
        found = json.loads(result.stdout)
        return Listing(
            found["notebooks_dir"],
            tuple(
                Notebook(n["lab"], n["kind"], n["language"], n["file"])
                for n in found["notebooks"]
            ),
        )
    except (ValueError, KeyError, TypeError):
        lines = (result.stderr or result.stdout).strip().splitlines()
        error = lines[-1] if lines else f"code {result.returncode}"
        return Listing("", (), error.replace(f"{workspace}/", ""))


def read(workspace: Path, file: str) -> dict[str, Any] | None:
    """The notebook as it is in the workspace.

    Returns:
        Its JSON, None if it's missing or isn't JSON.
    """
    try:
        return json.loads((workspace / file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def committed(workspace: Path, file: str) -> dict[str, Any] | None:
    """The notebook as of the workspace's last commit.

    Returns:
        Its JSON, None if the commit doesn't have it.
    """
    result = subprocess.run(
        ["git", "-C", str(workspace), "show", f"HEAD:{file}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def head(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def open_in_editor(path: Path) -> str | None:
    """Open the notebook with the application the system opens notebooks with.

    Returns:
        Why it couldn't, None if it did (or still is: an opener may wait \
        for the application to close).
    """
    if sys.platform == "win32":
        os.startfile(path)
        return None
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        process = subprocess.Popen(
            [opener, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return f"{opener} : {error}"
    try:
        _, stderr = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        # The application runs: whenever it ends, its exit is collected.
        Thread(target=process.wait, daemon=True).start()
        return None
    if process.returncode:
        message = stderr.decode(errors="replace").strip().splitlines()
        return (
            message[-1] if message else f"{opener} a échoué (code {process.returncode})"
        )
    return None
