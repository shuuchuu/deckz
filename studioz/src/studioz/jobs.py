"""Jobs: the long commands a person starts from studioz, run in the background.

A deck's full build, an upload, a publication: each is a job, its commands
(the workspace's own deckz, every option spelled out) run one after the
other, stopping at the first that fails. A workspace runs one job at a time,
in the order they were started (they write the same outputs); workspaces run
theirs side by side, deckz limiting the compilations machine-wide. A job's
log is kept to show, and a job can be stopped. Jobs live as long as studioz:
stopping it stops them.
"""

import os
import re
import signal
import subprocess
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from itertools import count
from pathlib import Path
from threading import Lock, Thread

from .watches import workspace_environment

_LOG_LINES = 2000
_STOP_GRACE = 5.0
# deckz's log lines end with where they were logged, alone on its line when
# the message wraps: noise in a job's log.
_LOCATION = re.compile(r"(?:^|\s{2,})[\w.-]+\.py:\d+$")


class JobState(Enum):
    QUEUED = "en attente"
    RUNNING = "en cours"
    DONE = "terminée"
    FAILED = "échouée"
    STOPPED = "arrêtée"


@dataclass(eq=False)
class Job:
    id: int
    workspace: Path
    title: str
    """What it does, in French: « Construire orsys/drn (fr, en) »."""
    steps: tuple[tuple[str, ...], ...]
    cwd: Path
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: JobState = JobState.QUEUED
    started: datetime | None = None
    ended: datetime | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=_LOG_LINES))
    process: subprocess.Popen[str] | None = None
    stopping: bool = False

    @property
    def finished(self) -> bool:
        return self.state in {JobState.DONE, JobState.FAILED, JobState.STOPPED}


class Jobs:
    """Every job studioz runs, each workspace's one after the other."""

    def __init__(self) -> None:
        self._jobs: list[Job] = []
        self._ids = count(1)
        self._lock = Lock()
        self._closed = False

    def submit(
        self,
        workspace: Path,
        title: str,
        steps: Sequence[Sequence[str]],
        cwd: Path | None = None,
    ) -> Job:
        """Queue a job, started at once if its workspace runs none.

        Args:
            workspace: The workspace it works on.
            title: What it does, in French.
            steps: Its commands, run in order until one fails.
            cwd: Where they run; the workspace by default.

        Returns:
            The job.
        """
        job = Job(
            next(self._ids),
            workspace,
            title,
            tuple(tuple(step) for step in steps),
            cwd or workspace,
        )
        with self._lock:
            self._jobs.append(job)
        self._start_next(workspace)
        return job

    def jobs(self, workspace: Path) -> list[Job]:
        """The workspace's jobs.

        Returns:
            Them, most recent first.
        """
        with self._lock:
            return [job for job in reversed(self._jobs) if job.workspace == workspace]

    def get(self, workspace: Path, job_id: int) -> Job | None:
        with self._lock:
            return next(
                (j for j in self._jobs if j.id == job_id and j.workspace == workspace),
                None,
            )

    def _start_next(self, workspace: Path) -> None:
        with self._lock:
            if self._closed:
                return
            mine = [job for job in self._jobs if job.workspace == workspace]
            if any(job.state is JobState.RUNNING for job in mine):
                return
            job = next((j for j in mine if j.state is JobState.QUEUED), None)
            if job is None:
                return
            job.state = JobState.RUNNING
            job.started = datetime.now(UTC)
        Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: Job) -> None:
        state = JobState.DONE
        for step in job.steps:
            code = self._run_step(job, step)
            if job.stopping:
                state = JobState.STOPPED
                break
            if code:
                job.log.append(f"(code de sortie {code})")
                state = JobState.FAILED
                break
        with self._lock:
            job.process = None
            job.state = state
            job.ended = datetime.now(UTC)
        self._start_next(job.workspace)

    def _run_step(self, job: Job, step: tuple[str, ...]) -> int:
        prefix = f"{job.workspace}/"
        job.log.append(f"$ {' '.join(step)}".replace(prefix, ""))
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
                job.log.append(str(error))
                return -1
        assert process.stdout is not None
        for line in process.stdout:
            # deckz names files by their absolute path.
            tidy = _LOCATION.sub("", line.rstrip()).rstrip().replace(prefix, "")
            if tidy:
                job.log.append(tidy)
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
                return
            process = job.process
        if process is not None:
            _terminate(process)

    def stop_all(self) -> None:
        with self._lock:
            self._closed = True
            running = [job for job in self._jobs if not job.finished]
            for job in running:
                job.stopping = True
            processes = [job.process for job in running if job.process]
        for process in processes:
            _terminate(process)


def _terminate(process: subprocess.Popen[str]) -> None:
    """Stop a step and what it started (deckz's Typst workers), gently first."""
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(_STOP_GRACE)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
