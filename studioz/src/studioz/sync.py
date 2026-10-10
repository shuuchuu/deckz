"""Syncing a workspace with the upstream branch: update, check, publish.

A workspace's commits go to the branch the main checkout tracks (its
upstream, e.g. `origin/main`), straight from the workspace: the main
checkout is never touched (other sessions may be working in it).

- **Update**: fetch, then rebase the workspace's commits onto the upstream
  branch, its uncommitted work carried along (`--autostash`: the workspace
  is the person's own). A conflict stops the rebase, never resolved
  silently: the person fixes the files (they hold git's conflict markers)
  and continues, or aborts, which puts everything back as it was.
- **Publish**: the commits are checked as they'll be pushed, not as the
  workspace's files are (`deckz check --staged` with an index holding the
  commit, and the `Lang-sync` rule on each commit, `deckz hooks
  check-commits`, as CI does), then pushed once the person confirms:
  exactly the commit checked (if the workspace's HEAD moved since, nothing
  is pushed), and never forced.

Every command runs in the workspace, the checks with its own deckz.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp

from .background import git
from .watches import environment
from .workspaces import STATE_DIR

_NETWORK_TIMEOUT = 180
_CHECK_TIMEOUT = 900
_MARKER = re.compile(r"^(<{7} |>{7} |={7}$)", re.MULTILINE)


@dataclass(frozen=True)
class Upstream:
    remote: str
    branch: str
    """The remote's branch, e.g. `main`."""
    tracking: str
    """Its remote-tracking ref, e.g. `refs/remotes/origin/main`."""

    @property
    def name(self) -> str:
        return f"{self.remote}/{self.branch}"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    author: str


@dataclass(frozen=True)
class State:
    upstream: Upstream
    ahead: tuple[Commit, ...]
    """The commits to publish, newest first."""
    behind: int
    """The upstream branch's commits the workspace lacks, as last fetched."""
    fetched: datetime | None
    """When the workspace last fetched."""
    conflicts: tuple[str, ...] | None
    """During a rebase, the files in conflict; None outside one."""


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str
    """What happened, in French."""
    output: str = ""
    """The commands' output, the workspace's paths made relative."""
    checked: str | None = None
    """The commit the checks passed on, which may now be published."""


def upstream(main: Path) -> Upstream | None:
    """The branch workspaces sync with: the main checkout's branch's upstream.

    Returns:
        It, None when the main checkout's branch has none (or isn't a branch).
    """
    branch = git(main, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return None
    found = git(
        main,
        "for-each-ref",
        "--format=%(upstream:remotename)%00%(upstream:remoteref)%00%(upstream)",
        f"refs/heads/{branch}",
    )
    parts = (found or "").split("\0")
    if len(parts) != 3 or not all(parts):
        return None
    remote, ref, tracking = parts
    return Upstream(remote, ref.removeprefix("refs/heads/"), tracking)


def _rebasing(workspace: Path) -> bool:
    return any(
        (workspace / (git(workspace, "rev-parse", "--git-path", marker) or "")).exists()
        for marker in ("rebase-merge", "rebase-apply")
    )


def conflicts(workspace: Path) -> tuple[str, ...]:
    found = git(workspace, "diff", "--name-only", "--diff-filter=U", "-z")
    return tuple(path for path in (found or "").split("\0") if path)


def state(workspace: Path, up: Upstream) -> State:
    """Where the workspace stands against the upstream branch, without fetching.

    Returns:
        Its commits to publish, how far behind, and its rebase's conflicts.
    """
    log = git(workspace, "log", "--format=%H%x00%s%x00%an", f"{up.tracking}..HEAD")
    ahead = tuple(
        Commit(*line.split("\0", 2)) for line in (log or "").splitlines() if line
    )
    behind = git(workspace, "rev-list", "--count", f"HEAD..{up.tracking}")
    fetch_head = workspace / (
        git(workspace, "rev-parse", "--git-path", "FETCH_HEAD") or ""
    )
    fetched = (
        datetime.fromtimestamp(fetch_head.stat().st_mtime, UTC)
        if fetch_head.is_file()
        else None
    )
    return State(
        up,
        ahead,
        int(behind or 0),
        fetched,
        conflicts(workspace) if _rebasing(workspace) else None,
    )


def _environment(workspace: Path, **extra: str) -> dict[str, str]:
    variables = environment()
    venv = workspace / ".venv" / "bin"
    if venv.is_dir():
        variables["PATH"] = f"{venv}{os.pathsep}{variables.get('PATH', '')}"
    # Nothing may wait for a password typed in a terminal nobody sees.
    variables["GIT_TERMINAL_PROMPT"] = "0"
    variables["GIT_EDITOR"] = "true"
    variables["GIT_LITERAL_PATHSPECS"] = "1"
    return variables | extra


def _run(
    workspace: Path,
    command: Sequence[str],
    timeout: float = _NETWORK_TIMEOUT,
    **extra: str,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=_environment(workspace, **extra),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1, f"{command[0]} {command[1]} : pas fini après {timeout // 60:.0f} min"
    return result.returncode, result.stdout.replace(f"{workspace}/", "").strip()


def fetch(workspace: Path, up: Upstream) -> Outcome:
    code, output = _run(workspace, ["git", "fetch", "--quiet", up.remote])
    if code:
        return Outcome(False, f"Impossible de récupérer {up.name}.", output)
    return Outcome(True, f"{up.name} récupéré.")


def update(workspace: Path, up: Upstream) -> Outcome:
    """Fetch, then rebase the workspace's commits onto the upstream branch.

    Returns:
        How it went: a conflict stops the rebase, its files to fix.
    """
    if _rebasing(workspace):
        return Outcome(
            False, "Un rebase est déjà en cours : continuez-le ou abandonnez-le."
        )
    fetched = fetch(workspace, up)
    if not fetched.ok:
        return fetched
    behind = state(workspace, up).behind
    if not behind:
        # The dialog already says where the workspace stands.
        return Outcome(True, "")
    code, output = _run(workspace, ["git", "rebase", "--autostash", up.tracking])
    if _rebasing(workspace):
        return Outcome(
            False,
            "Conflit : un de vos commits et la branche amont changent les mêmes "
            "lignes. Corrigez les fichiers en conflit, puis continuez.",
            output,
        )
    if code:
        return Outcome(False, "La mise à jour a échoué.", output)
    if "autostash" in output.lower() and "conflict" in output.lower():
        return Outcome(
            False,
            "Vos commits sont à jour, mais vos modifications non committées entrent "
            "en conflit avec la branche amont : corrigez les fichiers marqués. "
            "Elles restent aussi dans « git stash list ».",
            output,
        )
    plural = "s" if behind > 1 else ""
    return Outcome(
        True,
        f"{behind} commit{plural} de {up.name} récupéré{plural}, "
        "vos commits replacés par-dessus.",
    )


def markers(workspace: Path, paths: Sequence[str]) -> list[str]:
    """The files among `paths` still holding conflict markers.

    Returns:
        Their paths.
    """
    found = []
    for path in paths:
        file = workspace / path
        try:
            text = file.read_text(encoding="utf8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            continue
        if _MARKER.search(text):
            found.append(path)
    return found


def continue_rebase(workspace: Path) -> Outcome:
    """Take the conflicts' files as they are now, and go on with the rebase.

    Returns:
        How it went: the next commit may conflict too.
    """
    if not _rebasing(workspace):
        return Outcome(False, "Aucun rebase en cours.")
    pending = conflicts(workspace)
    if left := markers(workspace, pending):
        return Outcome(
            False,
            "Des marqueurs de conflit (<<<<<<<, =======, >>>>>>>) restent dans : "
            + ", ".join(left),
        )
    if pending:
        code, output = _add(workspace, pending)
        if code:
            return Outcome(
                False, "Impossible de prendre les fichiers corrigés.", output
            )
    code, output = _run(workspace, ["git", "rebase", "--continue"])
    if _rebasing(workspace):
        return Outcome(
            False,
            "Le commit suivant est en conflit à son tour : corrigez-le, puis "
            "continuez.",
            output,
        )
    if code:
        return Outcome(False, "Le rebase n'a pas pu continuer.", output)
    return Outcome(True, "Mise à jour terminée.")


def _add(workspace: Path, paths: Sequence[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "add", "--all", "--pathspec-from-file=-", "--pathspec-file-nul"],
        cwd=workspace,
        env=_environment(workspace),
        input="\0".join(paths),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def abort(workspace: Path) -> Outcome:
    """Abandon the rebase: the workspace goes back to where it was before.

    Returns:
        How it went.
    """
    if not _rebasing(workspace):
        return Outcome(False, "Aucun rebase en cours.")
    code, output = _run(workspace, ["git", "rebase", "--abort"])
    if code:
        return Outcome(False, "Impossible d'abandonner le rebase.", output)
    return Outcome(True, "Mise à jour abandonnée : l'espace est comme avant.")


def check(workspace: Path, up: Upstream, sha: str) -> Outcome:
    """Check the commits up to `sha` as they would be pushed.

    `deckz check --staged`, run by the workspace's own deckz with an index
    holding `sha` (whatever the workspace's files are), then the `Lang-sync`
    rule on each commit not on the upstream branch.

    Returns:
        Whether they pass, with the checks' output.
    """
    deckz = str(workspace / ".venv" / "bin" / "deckz")
    scratch = workspace / STATE_DIR
    scratch.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="push-index-", dir=scratch))
    try:
        index = str(directory / "index")
        code, output = _run(workspace, ["git", "read-tree", sha], GIT_INDEX_FILE=index)
        if code:
            return Outcome(False, "Impossible de préparer la vérification.", output)
        code, output = _run(
            workspace,
            [deckz, "check", "--staged", "--plain"],
            _CHECK_TIMEOUT,
            GIT_INDEX_FILE=index,
        )
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if code:
        return Outcome(False, "Les vérifications ont trouvé des problèmes.", output)
    code, trailers = _run(
        workspace, [deckz, "hooks", "check-commits", f"{up.tracking}..{sha}"]
    )
    if code:
        return Outcome(
            False, "Un commit change une seule langue sans trailer Lang-sync.", trailers
        )
    return Outcome(True, "Les vérifications passent.", output, sha)


def prepare(workspace: Path, up: Upstream) -> Outcome:
    """Update the workspace, then check its commits as they would be pushed.

    Returns:
        How it went, with the commit checked if the checks pass.
    """
    updated = update(workspace, up)
    if not updated.ok:
        return updated
    if not state(workspace, up).ahead:
        return Outcome(True, f"{updated.message} Aucun commit à publier.".strip())
    checked = check(workspace, up, git(workspace, "rev-parse", "HEAD") or "")
    return Outcome(
        checked.ok,
        f"{updated.message} {checked.message}".strip(),
        checked.output,
        checked.checked,
    )


def publish(workspace: Path, up: Upstream, sha: str) -> Outcome:
    """Push `sha` to the upstream branch, if it's still the workspace's HEAD.

    Returns:
        How it went: refused if HEAD moved since it was checked, or if the \
        upstream branch moved since the last update (never forced).
    """
    if git(workspace, "rev-parse", "HEAD") != sha:
        return Outcome(
            False,
            "L'espace a changé depuis la vérification : vérifiez à nouveau.",
        )
    code, output = _run(
        workspace,
        ["git", "push", "--quiet", up.remote, f"{sha}:refs/heads/{up.branch}"],
    )
    if code:
        rejected = "rejected" in output or "non-fast-forward" in output
        return Outcome(
            False,
            f"{up.name} a reçu d'autres commits entre-temps : mettez à jour, puis "
            "vérifiez et publiez à nouveau."
            if rejected
            else f"La publication sur {up.name} a échoué.",
            output,
        )
    return Outcome(True, f"Publié sur {up.name}.")
