"""Committing a workspace's changes: the files the person chose, as they are.

The person picks files, never hunks: the commit holds each chosen file as it
is in the workspace (whatever was staged before, in a terminal, is unstaged
first; the files themselves are never touched). git's own hooks run as
usual, by the workspace's own deckz (`deckz check --staged`, and the
commit-msg hook's `Lang-sync` rule), and their refusal is shown as is: it
names its fix.

The `Lang-sync` rule is deckz's (`deckz.analyzing.i18n_stale.one_sided`):
studioz asks before the hook does, and writes the trailer the person chose.
"""

import subprocess
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from deckz.analyzing.i18n_stale import OneSidedChange

from .background import Change, git
from .watches import workspace_environment

_TIMEOUT = 900
LANG_SYNC_CHOICES = ("pending", "only")
"""The ways out the commit-msg hook offers, but porting the change."""


@dataclass(frozen=True)
class Committed:
    sha: str
    subject: str


@dataclass(frozen=True)
class Refused:
    output: str
    """git's, and its hooks', with the workspace's paths made relative."""


def blocked(workspace: Path, found: Sequence[Change]) -> str | None:
    """Why the workspace can't be committed from studioz right now.

    Returns:
        The reason, in French, None if it can.
    """
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        path = git(workspace, "rev-parse", "--git-path", marker)
        if path and (workspace / path).exists():
            return (
                "Un rebase ou une fusion est en cours dans cet espace : "
                "terminez-le d'abord."
            )
    if any("U" in c.status or c.status in {"AA", "DD"} for c in found):
        return "Des fichiers sont en conflit : résolvez-les d'abord."
    return None


def to_stage(found: Sequence[Change], selected: Collection[str]) -> list[str]:
    """The paths a commit of `selected` stages: a rename's original too.

    Returns:
        Them, in `git status`'s order.
    """
    paths = []
    for change in found:
        if change.path in selected:
            paths.append(change.path)
            if change.original is not None:
                paths.append(change.original)
    return paths


def lang_sync_trailer(
    one_sided: Sequence[OneSidedChange], choice: str, reason: str
) -> str:
    """The `Lang-sync` trailer's value for the person's choice.

    Args:
        one_sided: The pairs the commit changes on one side only.
        choice: `pending` (the other language comes in a later commit) or \
            `only` (nothing to port, for `reason`).
        reason: Why, for `only`.

    Returns:
        The value, e.g. `fr-only (une coquille)`.

    Raises:
        ValueError: With what's missing, in French.
    """
    if choice == "pending":
        return "pending"
    if choice != "only":
        msg = (
            "Ces fichiers changent sans leur version dans l'autre langue : "
            "cochez-la aussi, ou dites pourquoi."
        )
        raise ValueError(msg)
    sides = {change.changed for change in one_sided}
    if len(sides) != 1:
        msg = (
            "Ce commit change des fichiers français seuls et des fichiers "
            "anglais seuls : « rien à traduire » ne vaut que pour une langue."
        )
        raise ValueError(msg)
    reason = " ".join(reason.split())
    if not reason:
        msg = "Dites pourquoi il n'y a rien à traduire."
        raise ValueError(msg)
    return f"{sides.pop()}-only ({reason})"


def _run(
    workspace: Path, args: Sequence[str], text: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        input=text,
        env=workspace_environment(workspace, GIT_LITERAL_PATHSPECS="1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=_TIMEOUT,
        check=False,
    )


def commit(
    workspace: Path, paths: Sequence[str], message: str, trailer: str | None
) -> Committed | Refused:
    """Commit `paths`, as they are in the workspace, and nothing else.

    Args:
        workspace: The workspace.
        paths: The paths to commit (`to_stage`), relative to it.
        message: The commit message.
        trailer: The `Lang-sync` trailer's value to add, if any.

    Returns:
        The commit, or git's refusal (a hook's, typically).
    """
    trailers = ["--trailer", f"Lang-sync: {trailer}"] if trailer else []
    steps = (
        (["reset", "--quiet"], ""),
        (
            ["add", "--all", "--pathspec-from-file=-", "--pathspec-file-nul"],
            "\0".join(paths),
        ),
        (["commit", "--file=-", *trailers], message),
    )
    for args, text in steps:
        try:
            result = _run(workspace, args, text)
        except subprocess.TimeoutExpired:
            return Refused(f"git {args[0]} : pas fini après {_TIMEOUT // 60} min")
        if result.returncode:
            output = result.stdout.replace(f"{workspace}/", "").strip()
            return Refused(output or f"git {args[0]} : code {result.returncode}")
    sha = git(workspace, "rev-parse", "HEAD") or ""
    return Committed(sha, message.strip().splitlines()[0])
