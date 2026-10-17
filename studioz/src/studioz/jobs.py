"""Jobs: the long commands a person starts from studioz, run in the background.

A deck's full build, an upload, a publication: each is a job, its commands
(the workspace's own deckz, every option spelled out) run one after the
other, stopping at the first that fails. A workspace runs one job at a time
in each lane, in the order they were started (a lane's jobs write the same
outputs); workspaces run theirs side by side, deckz limiting the compilations
machine-wide. A GPU pass has a lane of its own: it lasts an hour and writes
only notebooks, and the builds needn't wait for it. A job's log is kept to
show, and a job can be stopped.

Each job's record and log are kept in its workspace's `.run/studioz/jobs/`
(the last `_KEPT`), so that they outlive studioz: stopping studioz stops its
jobs, and those it stopped, or a crash left running, are "interrompues" when
it starts again. A job that may simply run again (a build) says so
(`rerun`); one that must be confirmed again (an upload, a publication) names
the dialog that starts it (`form`).
"""

import json
import os
import re
import signal
import subprocess
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from .watches import workspace_environment

_LOG_LINES = 2000
_STOP_GRACE = 5.0
_STOP_GRACES = {"gpu": 300.0}
"""A lane's grace, when longer: a GPU pass stopped destroys its machine first \
(`deckz labs gpu pass`), and killed meanwhile it would leave it billing."""
_KEPT = 30
"""The jobs kept per workspace, the most recent."""
# deckz's log lines end with where they were logged, alone on its line when
# the message wraps: noise in a job's log.
_LOCATION = re.compile(r"(?:^|\s{2,})[\w.-]+\.py:\d+$")
# And start with when and how loud: noise in a notification.
_LEVEL = re.compile(r"^\d\d:\d\d:\d\d\s+(?:CRITICAL|ERROR|WARNING|INFO|DEBUG)\s+")


def tidy(line: str) -> str:
    """A deckz log line without when, how loud nor where it was logged.

    Returns:
        Its message.
    """
    return _LEVEL.sub("", _LOCATION.sub("", line.rstrip()).rstrip())


class JobState(Enum):
    QUEUED = "en attente"
    RUNNING = "en cours"
    DONE = "terminée"
    FAILED = "échouée"
    STOPPED = "arrêtée"
    INTERRUPTED = "interrompue"
    """Stopped by studioz's own end, or left running by a crash."""


@dataclass(eq=False)
class Job:
    id: int
    workspace: Path
    title: str
    """What it does, in French: « Construire orsys/drn (fr, en) »."""
    steps: tuple[tuple[str, ...], ...]
    cwd: Path
    rerun: bool = False
    """Whether it may run again as is, from its log."""
    form: str | None = None
    """The dialog starting it again, when it must be confirmed again."""
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: JobState = JobState.QUEUED
    started: datetime | None = None
    ended: datetime | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_LINES))
    process: subprocess.Popen[str] | None = None
    stopping: bool = False
    interrupted: bool = False
    lane: str = ""
    """Jobs of one lane run one after the other; lanes side by side."""
    link: tuple[str, str] | None = None
    """What to see once it ended (a label, a URL): a notebook's before/after."""

    @property
    def finished(self) -> bool:
        return self.state not in {JobState.QUEUED, JobState.RUNNING}

    @property
    def failure(self) -> str:
        """Its log's last line before its exit code, said when it failed."""
        lines = [line for line in self.log if not line.startswith("(code de sortie")]
        if not lines or self.state is not JobState.FAILED:
            return ""
        return _LEVEL.sub("", lines[-1])

    def record(self) -> dict[str, Any]:
        def when(moment: datetime | None) -> str | None:
            return moment.isoformat() if moment else None

        return {
            "id": self.id,
            "title": self.title,
            "steps": self.steps,
            "cwd": str(self.cwd),
            "rerun": self.rerun,
            "form": self.form,
            "created": when(self.created),
            "started": when(self.started),
            "ended": when(self.ended),
            "state": self.state.name,
            "lane": self.lane,
            "link": self.link,
        }


def _store(workspace: Path) -> Path:
    return workspace / ".run" / "studioz" / "jobs"


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _load(workspace: Path) -> list[Job]:
    """The workspace's jobs as kept, the unfinished ones now interrupted.

    Returns:
        Them, oldest first; an unreadable record is skipped.
    """
    store = _store(workspace)
    found = []
    for path in store.glob("*.json") if store.is_dir() else ():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            job = Job(
                int(record["id"]),
                workspace,
                record["title"],
                tuple(tuple(step) for step in record["steps"]),
                Path(record["cwd"]),
                bool(record.get("rerun")),
                record.get("form"),
                _when(record["created"]) or datetime.now(UTC),
                JobState[record["state"]],
                _when(record.get("started")),
                _when(record.get("ended")),
                lane=str(record.get("lane") or ""),
                link=tuple(record["link"]) if record.get("link") else None,
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        log = path.with_suffix(".log")
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace")
            job.log.extend(text.splitlines())
        if not job.finished:
            job.state = JobState.INTERRUPTED
            job.ended = job.ended or datetime.now(UTC)
            _save(job)
        found.append(job)
    return sorted(found, key=lambda job: job.id)


def _save(job: Job) -> None:
    store = _store(job.workspace)
    try:
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{job.id}.json").write_text(
            json.dumps(job.record(), ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass  # Kept in memory still: a workspace gone, a full disk.


def _append(job: Job, line: str) -> None:
    job.log.append(line)
    try:
        with (_store(job.workspace) / f"{job.id}.log").open(
            "a", encoding="utf-8"
        ) as log:
            log.write(line + "\n")
    except OSError:
        pass


def _forget(job: Job) -> None:
    for suffix in (".json", ".log"):
        (_store(job.workspace) / f"{job.id}{suffix}").unlink(missing_ok=True)


class Jobs:
    """Every job studioz runs, each workspace's one after the other."""

    def __init__(self) -> None:
        self._jobs: list[Job] = []
        self._loaded: set[Path] = set()
        self._lock = Lock()
        self._closed = False

    def _known(self, workspace: Path) -> list[Job]:
        """The workspace's jobs, those kept from before loaded first.

        Called holding the lock.

        Returns:
            Them, oldest first.
        """
        if workspace not in self._loaded:
            self._loaded.add(workspace)
            self._jobs[:0] = _load(workspace)
        return [job for job in self._jobs if job.workspace == workspace]

    def submit(
        self,
        workspace: Path,
        title: str,
        steps: Sequence[Sequence[str]],
        cwd: Path | None = None,
        *,
        rerun: bool = False,
        form: str | None = None,
        lane: str = "",
        link: tuple[str, str] | None = None,
    ) -> Job:
        """Queue a job, started at once if its workspace's lane runs none.

        Args:
            workspace: The workspace it works on.
            title: What it does, in French.
            steps: Its commands, run in order until one fails.
            cwd: Where they run; the workspace by default.
            rerun: Whether it may run again as is, without a confirmation.
            form: The dialog starting it again, when it needs one.
            lane: Its lane: `gpu` for a GPU pass, else the builds' one.
            link: What to see once it ended (a label, a URL).

        Returns:
            The job.
        """
        with self._lock:
            mine = self._known(workspace)
            job = Job(
                max((known.id for known in mine), default=0) + 1,
                workspace,
                title,
                tuple(tuple(step) for step in steps),
                cwd or workspace,
                rerun,
                form,
                lane=lane,
                link=link,
            )
            self._jobs.append(job)
            # The oldest finished ones go, records and logs.
            for old in [known for known in mine if known.finished][: -_KEPT + 1]:
                self._jobs.remove(old)
                _forget(old)
        _save(job)
        self._start_next(workspace, lane)
        return job

    def rerun(self, workspace: Path, job_id: int) -> Job | None:
        """Run a finished job again, if it may run again as is.

        Returns:
            The new job, or None.
        """
        job = self.get(workspace, job_id)
        if job is None or not job.finished or not job.rerun:
            return None
        return self.submit(
            workspace,
            job.title,
            job.steps,
            job.cwd,
            rerun=True,
            lane=job.lane,
            link=job.link,
        )

    def jobs(self, workspace: Path) -> list[Job]:
        """The workspace's jobs.

        Returns:
            Them, most recent first.
        """
        with self._lock:
            return list(reversed(self._known(workspace)))

    def get(self, workspace: Path, job_id: int) -> Job | None:
        with self._lock:
            return next((j for j in self._known(workspace) if j.id == job_id), None)

    def _start_next(self, workspace: Path, lane: str) -> None:
        with self._lock:
            if self._closed:
                return
            mine = [job for job in self._known(workspace) if job.lane == lane]
            if any(job.state is JobState.RUNNING for job in mine):
                return
            job = next((j for j in mine if j.state is JobState.QUEUED), None)
            if job is None:
                return
            job.state = JobState.RUNNING
            job.started = datetime.now(UTC)
        _save(job)
        Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: Job) -> None:
        state = JobState.DONE
        for step in job.steps:
            code = self._run_step(job, step)
            if job.stopping:
                state = JobState.INTERRUPTED if job.interrupted else JobState.STOPPED
                break
            if code:
                _append(job, f"(code de sortie {code})")
                state = JobState.FAILED
                break
        with self._lock:
            job.process = None
            job.state = state
            job.ended = datetime.now(UTC)
        _save(job)
        self._start_next(job.workspace, job.lane)

    def _run_step(self, job: Job, step: tuple[str, ...]) -> int:
        prefix = f"{job.workspace}/"
        _append(job, f"$ {' '.join(step)}".replace(prefix, ""))
        with self._lock:
            if job.stopping or self._closed:
                job.stopping = True
                return -1
            try:
                job.process = process = subprocess.Popen(
                    step,
                    cwd=job.cwd,
                    env=workspace_environment(job.workspace),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    start_new_session=True,
                )
            except OSError as error:
                _append(job, str(error))
                return -1
        assert process.stdout is not None
        for line in process.stdout:
            # deckz names files by their absolute path.
            tidy = _LOCATION.sub("", line.rstrip()).rstrip().replace(prefix, "")
            if tidy:
                _append(job, tidy)
        return process.wait()

    def stop(self, workspace: Path, job_id: int) -> None:
        """Stop a job: a queued one never starts, a running one is killed."""
        job = self.get(workspace, job_id)
        if job is None or job.finished:
            return
        with self._lock:
            job.stopping = True
            if job.state is JobState.QUEUED:
                job.state = JobState.STOPPED
                job.ended = datetime.now(UTC)
                _save(job)
                return
            process = job.process
        if process is None:
            return
        grace = _STOP_GRACES.get(job.lane, _STOP_GRACE)
        if grace > _STOP_GRACE:
            # Not in the request: the job's own reloads show it end.
            Thread(target=_terminate, args=(process, grace), daemon=True).start()
        else:
            _terminate(process, grace)

    def stop_all(self) -> None:
        """Stop every job as studioz ends: they're kept as interrupted."""
        with self._lock:
            self._closed = True
            running = [job for job in self._jobs if not job.finished]
            for job in running:
                job.stopping = job.interrupted = True
                if job.state is JobState.QUEUED:
                    job.state = JobState.INTERRUPTED
                    job.ended = datetime.now(UTC)
                    _save(job)
            processes = [
                (job.process, _STOP_GRACES.get(job.lane, _STOP_GRACE))
                for job in running
                if job.process
            ]
        for process, grace in processes:
            _terminate(process, grace)


def _terminate(process: subprocess.Popen[str], grace: float) -> None:
    """Stop a step and what it started (deckz's Typst workers), gently first."""
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
