"""Baselines: each deck's handout as of the workspace's last commit.

The Changes view compares the deck on screen with its baseline, under
`.run/studioz/baselines/<commit>/<deck>/<lang>/`: the handout PDF, and the
title of each frame page (`frames.json`, from what its build recorded). Only
the last commit's baselines are kept. A baseline comes:

- from the live build (`studioz.watches`), when it finishes while the
  workspace has no change since its last commit: that build is the commit's
  (`Baselines.capture`), at no cost;
- otherwise from a build of the committed version, in the background, in a
  scratch checkout of the commit next to the workspace
  (`<workspace>.baseline`, detached, seeded from the workspace as `deckz
  worktree add` seeds a worktree, removed once built), by the workspace's own
  deckz: a few seconds of copying, plus the deck's build.
"""

import json
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from threading import Lock, Thread

from deckz.analyzing.frames import frames
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.exceptions import DeckzError
from deckz.models import Lang
from deckz.worktrees import seed

from .background import changes, git
from .watches import build_command, environment, handout
from .workspaces import STATE_DIR

BASELINES_DIR = STATE_DIR / "baselines"
"""Relative to a workspace."""

_FRAMES = "frames.json"
_PDF = "handout.pdf"
_TIMEOUT = 1800
_ERROR_LINES = 12


@dataclass(frozen=True)
class Baseline:
    commit: str
    pdf: Path | None
    """The handout; None if the deck didn't exist at that commit."""
    titles: dict[int, str]
    """Each frame page's title."""


@dataclass(frozen=True)
class BaselineState:
    commit: str
    baseline: Baseline | None
    building: bool = False
    error: str | None = None
    """Why building it failed."""


def head(workspace: Path) -> str:
    """The workspace's last commit.

    Returns:
        Its hash, empty if git fails.
    """
    return git(workspace, "rev-parse", "HEAD") or ""


def _directory(workspace: Path, commit: str, deck: str, lang: Lang) -> Path:
    return workspace / BASELINES_DIR / commit / deck / lang


def _load(directory: Path, commit: str) -> Baseline | None:
    try:
        recorded = json.loads((directory / _FRAMES).read_text(encoding="utf8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    pdf = directory / _PDF
    return Baseline(
        commit,
        pdf if pdf.is_file() else None,
        {frame["page"]: frame["title"] for frame in recorded},
    )


def _store(
    workspace: Path, commit: str, deck: str, lang: Lang, built: Path | None
) -> None:
    """Keep the handout of `built`, `deck` built at `commit`, as its baseline.

    Args:
        workspace: The workspace.
        commit: The commit.
        deck: The deck, relative to the checkout.
        lang: The handout's language.
        built: The deck's directory in the checkout that built it, whose \
            build recorded its frames (else `DeckzError`); None if the deck \
            didn't exist at `commit`.
    """
    pdf = None if built is None else handout(built, lang)
    titles: list[dict[str, object]] = []
    if built is not None and pdf is not None:
        titles = [
            {"page": frame.page, "title": frame.title}
            for frame in frames(DeckSettings.from_yaml(built), pdf, query=False)
        ]
    directory = _directory(workspace, commit, deck, lang)
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Written aside, then moved in place: a baseline is whole or absent.
    partial = Path(mkdtemp(prefix=f".{lang}-", dir=directory.parent))
    if pdf is not None:
        shutil.copyfile(pdf, partial / _PDF)
    (partial / _FRAMES).write_text(json.dumps(titles), encoding="utf8")
    shutil.rmtree(directory, ignore_errors=True)
    partial.rename(directory)
    for other in (workspace / BASELINES_DIR).iterdir():
        if other.name != commit:
            shutil.rmtree(other, ignore_errors=True)


def _error(output: str) -> str:
    """What a failed build's output says went wrong.

    Returns:
        Its lines from the first error on, else its last lines.
    """
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if " ERROR " in line or " CRITICAL " in line:
            return "\n".join(lines[index : index + _ERROR_LINES])
    return "\n".join(lines[-_ERROR_LINES:]) or "la construction a échoué"


def scratch_path(workspace: Path) -> Path:
    """Where the workspace's baselines are built.

    Returns:
        `<workspace>.baseline`, next to it, as checkouts are.
    """
    return workspace.with_name(f"{workspace.name}.baseline")


def _remove_scratch(workspace: Path) -> None:
    scratch = scratch_path(workspace)
    if scratch.exists():
        git(workspace, "worktree", "remove", "--force", str(scratch))
        shutil.rmtree(scratch, ignore_errors=True)
    git(workspace, "worktree", "prune")


@dataclass
class _Job:
    error: str | None = None
    done: bool = False
    process: subprocess.Popen[str] | None = None


@dataclass
class _Workspace:
    lock: Lock = field(default_factory=Lock)
    """Held while its scratch checkout is in use: one build at a time."""
    jobs: dict[tuple[str, str, Lang], _Job] = field(default_factory=dict)


class Baselines:
    """The workspaces' baselines, built in the background when missing."""

    def __init__(self, command=build_command) -> None:
        """Prepare the builds.

        Args:
            command: `build_command`, which tests replace.
        """
        self._command = command
        self._workspaces: dict[Path, _Workspace] = {}
        self._lock = Lock()
        self._stopping = False

    def _state(self, workspace: Path) -> _Workspace:
        with self._lock:
            return self._workspaces.setdefault(workspace, _Workspace())

    def capture(self, workspace: Path, deck: Path, lang: Lang) -> bool:
        """Keep the deck's last build as its baseline, if it's the commit's.

        It is when the workspace has no change since its last commit: call it
        once a build of the deck in the workspace finished.

        Returns:
            Whether it was kept, which it isn't when there's a baseline already.
        """
        commit = head(workspace)
        name = deck.relative_to(workspace).as_posix()
        if not commit or changes(workspace):
            return False
        if _load(_directory(workspace, commit, name, lang), commit) is not None:
            return False
        try:
            _store(workspace, commit, name, lang, deck)
        except (DeckzError, OSError):
            return False
        return True

    def get(self, workspace: Path, deck: Path, lang: Lang) -> BaselineState:
        """The deck's baseline, its build started if it's missing.

        Returns:
            The baseline, or whether it's being built, or why that failed.
        """
        commit = head(workspace)
        name = deck.relative_to(workspace).as_posix()
        found = _load(_directory(workspace, commit, name, lang), commit)
        if found is not None:
            return BaselineState(commit, found)
        state = self._state(workspace)
        with self._lock:
            job = state.jobs.get((commit, name, lang))
            if job is not None and job.done and job.error is None:
                found = _load(_directory(workspace, commit, name, lang), commit)
                if found is not None:
                    return BaselineState(commit, found)
                # Removed since it was built: built again.
                job = None
            if job is None:
                job = state.jobs[commit, name, lang] = _Job()
                Thread(
                    target=self._build,
                    args=(workspace, state, job, commit, name, lang),
                    daemon=True,
                ).start()
            return BaselineState(commit, None, building=not job.done, error=job.error)

    def retry(self, workspace: Path, deck: Path, lang: Lang) -> None:
        """Forget a failed build of the deck's baseline, so that `get` starts one."""
        name = deck.relative_to(workspace).as_posix()
        state = self._state(workspace)
        with self._lock:
            job = state.jobs.get((head(workspace), name, lang))
            if job is not None and job.done:
                del state.jobs[head(workspace), name, lang]

    def _build(
        self,
        workspace: Path,
        state: _Workspace,
        job: _Job,
        commit: str,
        deck: str,
        lang: Lang,
    ) -> None:
        with state.lock:
            try:
                job.error = self._build_in_scratch(workspace, job, commit, deck, lang)
            except (DeckzError, OSError) as error:
                job.error = str(error)
            finally:
                _remove_scratch(workspace)
                job.done = True

    def _build_in_scratch(
        self, workspace: Path, job: _Job, commit: str, deck: str, lang: Lang
    ) -> str | None:
        if self._stopping:
            return "studioz s'arrête"
        scratch = scratch_path(workspace)
        _remove_scratch(workspace)
        added = git(
            workspace, "worktree", "add", "--detach", "--quiet", str(scratch), commit
        )
        if added is None:
            return f"impossible d'extraire le commit {commit[:7]} dans {scratch}"
        directory = scratch / deck
        if not (directory / "deck.yml").is_file():
            # A new deck: everything in it is new.
            _store(workspace, commit, deck, lang, None)
            return None
        seed(workspace, scratch, GlobalSettings.from_yaml(workspace).worktree.seed)
        with self._lock:
            if self._stopping:
                return "studioz s'arrête"
            job.process = process = subprocess.Popen(
                self._command(workspace, lang),
                cwd=directory,
                env=environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        try:
            output, _ = process.communicate(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
        if process.returncode:
            return _error(output).replace(f"{scratch}/", "")
        _store(workspace, commit, deck, lang, directory)
        return None

    def stop_all(self) -> None:
        """Stop the builds under way; their scratch checkouts are removed."""
        with self._lock:
            self._stopping = True
            processes = [
                job.process
                for state in self._workspaces.values()
                for job in state.jobs.values()
                if job.process is not None
            ]
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
