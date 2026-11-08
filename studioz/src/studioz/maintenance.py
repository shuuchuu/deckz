"""The Maintenance page: the workspace's own `deckz dashboard --json`, on demand.

The dashboard reads the whole repository (about 15 s on a large one), so it
runs only when the person asks, from the page's button: never by itself, not
on a file change, not when the page opens. Its last result is kept with when
it was computed in the workspace's `.run/studioz/maintenance.json`, shown until
the next run, across restarts. deckz decides everything shown: the decks'
order, the past INTRA decks left out (no `--all`), which sections need care,
and the file each row opens (`opens`); studioz lays it out.
"""

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Lock, Thread
from typing import Any

from .watches import environment

RESULT = Path(".run") / "studioz" / "maintenance.json"
"""Where a workspace's last dashboard is kept, relative to it."""

_TIMEOUT = 600

WHY = {
    "chapter_due": "chapitre dû",
    "chapter": "chapitre",
    "report": "rapport",
    "file": "diapositives",
}
"""What a row opens, on screen (deckz's `Opens.why`)."""

SECTION_STATES = {
    "fresh": "à jour",
    "due": "dues (règle)",
    "partial": "partielles",
    "stale": "périmées",
    "none": "sans rapport",
}
"""deckz's section states, on screen, in its order: the totals'."""

SECTION_STATE = {
    "fresh": "à jour",
    "due": "due (règle)",
    "partial": "partielle",
    "stale": "périmée",
    "none": "sans rapport",
}
"""A section row's state."""

FILE_STATES = {
    "fresh": "à jour",
    "due": "dus (règle)",
    "stale": "périmés",
    "unreviewed": "jamais relus",
    "deleted": "supprimés",
}

WHY_TITLES = {
    "chapter_due": "Le chapitre du support relu avant une règle ajoutée depuis",
    "chapter": "Le chapitre du support du premier fichier à revoir",
    "report": "Le rapport de relecture",
    "file": "Le premier fichier à revoir, qui n'a ni chapitre ni rapport",
}


@dataclass(frozen=True)
class Result:
    computed: datetime
    """When the run finished."""
    data: dict[str, Any]
    """`deckz dashboard --json`'s object."""

    @property
    def sections(self) -> list[dict[str, Any]]:
        """The sections needing care, by score, as deckz orders them."""
        return [s for s in self.data.get("sections", ()) if _needs_care(s)]

    @property
    def deck_root(self) -> str:
        """The folder every deck shown is in, with its slash, or "": not repeated."""
        folders = [
            PurePosixPath(deck["deck"]).parent.parts for deck in self.data["decks"]
        ]
        common: tuple[str, ...] = ()
        if folders:
            for parts in zip(*folders, strict=False):
                if len(set(parts)) > 1:
                    break
                common = (*common, parts[0])
            # A deck at the root of the folder keeps its own name.
            common = common[: min(len(f) for f in folders)]
        return f"{PurePosixPath(*common)}/" if common else ""


def _needs_care(section: dict[str, Any]) -> bool:
    # deckz says (`needs_care`); a workspace's older deckz didn't.
    if "needs_care" in section:
        return bool(section["needs_care"])
    findings = section.get("findings") or {}
    return (
        section.get("state") != "fresh"
        or bool(findings.get("total"))
        or bool((section.get("dated_facts") or {}).get("due"))
    )


@dataclass(frozen=True)
class State:
    result: Result | None
    """The last run's, None before the first one."""
    running: bool
    error: str | None = None
    """Why the last run failed (its result is the one before)."""


def read(workspace: Path) -> Result | None:
    """The workspace's last dashboard.

    Returns:
        It, None if none was computed or the file doesn't read.
    """
    try:
        kept = json.loads((workspace / RESULT).read_text(encoding="utf8"))
        return Result(datetime.fromisoformat(kept["computed"]), kept["dashboard"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(workspace: Path, result: Result) -> None:
    path = workspace / RESULT
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"computed": result.computed.isoformat(), "dashboard": result.data}),
        encoding="utf8",
    )
    temporary.replace(path)


class Maintenance:
    """Each workspace's dashboard runs, one at a time per workspace."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._running: dict[Path, subprocess.Popen[str] | None] = {}
        self._errors: dict[Path, str] = {}

    def state(self, workspace: Path) -> State:
        """What the page shows.

        Returns:
            The last result, whether a run is under way, and why the last \
            one failed.
        """
        with self._lock:
            running = workspace in self._running
            error = self._errors.get(workspace)
        return State(read(workspace), running, error)

    def start(self, workspace: Path) -> bool:
        """Run the workspace's dashboard in the background.

        Returns:
            False if one was already running.
        """
        with self._lock:
            if workspace in self._running:
                return False
            self._running[workspace] = None
            self._errors.pop(workspace, None)
        Thread(target=self._run, args=(workspace,), daemon=True).start()
        return True

    def _run(self, workspace: Path) -> None:
        command = [str(workspace / ".venv" / "bin" / "deckz"), "dashboard", "--json"]
        error = None
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as failure:
            self._finish(workspace, str(failure))
            return
        with self._lock:
            self._running[workspace] = process
        try:
            out, err = process.communicate(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
        try:
            data = json.loads(out)
            if not isinstance(data, dict):
                raise TypeError(type(data).__name__)
            _write(workspace, Result(datetime.now(UTC), data))
        except (ValueError, TypeError, OSError):
            lines = (err or out).strip().splitlines()
            error = lines[-1] if lines else f"code {process.returncode}"
        self._finish(workspace, error)

    def _finish(self, workspace: Path, error: str | None) -> None:
        with self._lock:
            self._running.pop(workspace, None)
            if error is not None:
                self._errors[workspace] = error

    def stop_all(self) -> None:
        with self._lock:
            processes = [p for p in self._running.values() if p is not None]
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
