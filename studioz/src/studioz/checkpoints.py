"""Checkpoints: a workspace's files before and after an agent's turn, to undo it.

A snapshot is the tree git would commit from every file of the workspace
(`git add -A`, so ignored files are left out), written with a private index
(the workspace's own, copied the first time, so that git hashes only what
changed since). The workspace's index, HEAD and branch never move. A turn's
trees are kept under `refs/studioz/<workspace>/`, so that git's gc keeps
them, and what undoing needs in the conversation's directory.

Undoing a turn puts back the files it changed, and only those still as the
turn left them: one the person changed since is left alone, and said.
"""

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

_TIMEOUT = 120


@dataclass(frozen=True)
class Turn:
    """The checkpoints around a turn that changed files."""

    before: str
    """The tree before the turn."""
    after: str
    """The tree after it."""
    head: str
    """The workspace's HEAD after it: undoing is refused once it moved."""
    files: tuple[str, ...]
    """The files the turn changed, relative to the workspace."""


@dataclass(frozen=True)
class Undone:
    restored: tuple[str, ...]
    """The files put back as they were before the turn."""
    kept: tuple[str, ...]
    """Those changed since the turn, left as they are."""


def _git(workspace: Path, *args: str, index: Path | None = None) -> str:
    env = dict(os.environ)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=_TIMEOUT,
    ).stdout


def snapshot(workspace: Path, index: Path) -> str | None:
    """The tree of the workspace's files as they are.

    Args:
        workspace: The workspace.
        index: The private index to write it with.

    Returns:
        The tree's id, None if git couldn't tell (not a git checkout).
    """
    try:
        if not index.exists():
            own = _git(
                workspace, "rev-parse", "--path-format=absolute", "--git-path", "index"
            ).strip()
            index.parent.mkdir(parents=True, exist_ok=True)
            if Path(own).is_file():
                shutil.copyfile(own, index)
        _git(workspace, "add", "-A", index=index)
        return _git(workspace, "write-tree", index=index).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _changed(workspace: Path, before: str, after: str) -> tuple[str, ...]:
    names = _git(
        workspace, "diff-tree", "-r", "--no-renames", "--name-only", "-z", before, after
    )
    return tuple(name for name in names.split("\0") if name)


def _head(workspace: Path) -> str:
    return _git(workspace, "rev-parse", "HEAD").strip()


def record(workspace: Path, directory: Path, before: str, after: str) -> Turn | None:
    """Keep a turn's checkpoints, if it changed files.

    Args:
        workspace: The workspace.
        directory: Where the conversation keeps its state.
        before: The tree before the turn.
        after: The tree after it.

    Returns:
        The turn, None if it changed nothing (or git failed).
    """
    try:
        files = _changed(workspace, before, after) if before != after else ()
        if not files:
            return None
        turn = Turn(before, after, _head(workspace), files)
        for name, tree in (("avant", before), ("apres", after)):
            _git(workspace, "update-ref", f"{_refs(workspace)}/{name}", tree)
    except (OSError, subprocess.SubprocessError):
        return None
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "turn.json").write_text(json.dumps(asdict(turn)), encoding="utf8")
    return turn


def last(directory: Path) -> Turn | None:
    """The last turn recorded, which can be undone.

    Returns:
        It, None if there is none.
    """
    try:
        data = json.loads((directory / "turn.json").read_text(encoding="utf8"))
        return Turn(data["before"], data["after"], data["head"], tuple(data["files"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def forget(workspace: Path, directory: Path) -> None:
    """Forget the last turn: it can't be undone anymore."""
    (directory / "turn.json").unlink(missing_ok=True)
    for name in ("avant", "apres"):
        try:
            _git(workspace, "update-ref", "-d", f"{_refs(workspace)}/{name}")
        except (OSError, subprocess.SubprocessError):
            continue


def _refs(workspace: Path) -> str:
    return f"refs/studioz/{workspace.name}"


def _blobs(workspace: Path, tree: str, files: tuple[str, ...]) -> dict[str, str]:
    out = _git(workspace, "ls-tree", "-r", "-z", tree, "--", *files)
    found = {}
    for line in out.split("\0"):
        if line:
            meta, name = line.split("\t", 1)
            found[name] = meta
    return found


def undo(workspace: Path, index: Path, turn: Turn) -> Undone:
    """Put back the files `turn` changed, those still as it left them.

    Returns:
        The files put back, and those left as they are.

    Raises:
        UndoRefusedError: When the workspace's HEAD moved since the turn (the
            person committed), or git failed.
    """
    try:
        if _head(workspace) != turn.head:
            msg = (
                "Vous avez committé (ou synchronisé) depuis ce tour : il ne peut plus "
                "être annulé ici. Modifiez les fichiers, ou demandez-le à l'agent."
            )
            raise UndoRefusedError(msg)
        now = snapshot(workspace, index)
        if now is None:
            msg = "git n'a pas pu lire les fichiers de l'espace"
            raise UndoRefusedError(msg)
        after = _blobs(workspace, turn.after, turn.files)
        current = _blobs(workspace, now, turn.files)
        before = _blobs(workspace, turn.before, turn.files)
        restored = tuple(f for f in turn.files if after.get(f) == current.get(f))
        kept = tuple(f for f in turn.files if f not in restored)
        if back := [f for f in restored if f in before]:
            _git(
                workspace,
                "restore",
                f"--source={turn.before}",
                "--worktree",
                "--",
                *back,
            )
        for name in restored:
            if name not in before:
                (workspace / name).unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise UndoRefusedError(str(error)) from error
    return Undone(restored, kept)


class UndoRefusedError(Exception):
    """Why a turn can't be undone, in French."""
