"""Live builds: one `deckz run --watch` per workspace, for the deck on screen.

A watch keeps a Typst process per PDF alive, a few GB on a large deck, so
studioz watches only what someone looks at: the handout of one deck in one
language per workspace, started when its page opens, replaced when another
deck or language is opened there, and stopped once no page has followed it
for a while (`Watches.stop_idle`). It runs the workspace's own deckz, so it
goes through the machine-wide compilation limit like any other build.

What a page shows of a build comes from the watch's log, the one a person
sees in a terminal: deckz logs when a build starts, ends, or fails. A new PDF
is announced only once its build finished, never while it's being written.
"""

import os
import re
import signal
import subprocess
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from typing import IO

from deckz.configuring.settings import DeckSettings
from deckz.models import Lang, lang_dir
from deckz.utils import deck_name_from_dir

_LOG_LINES = 300
# A Rich log record: a time (blank when it's the previous one's), the level,
# the message, and where it was logged when the line is wide enough.
_RECORD = re.compile(
    r"(?:\d\d:\d\d:\d\d)?\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<message>.*?)(?:\s{2,}[\w.-]+\.py:\d+)?"
)
# deckz.pipelines.watch's messages.
_STARTED = frozenset({"Initial build", "Detected changes, starting a new build"})
_FINISHED = frozenset({"Initial build finished", "Build finished"})
_STOP_TIMEOUT = 5.0


class State(Enum):
    BUILDING = "building"
    BUILT = "built"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class Snapshot:
    """What a page shows of a watch at one moment."""

    state: State
    errors: tuple[str, ...]
    """The failed build's error lines, empty unless FAILED."""
    built: int
    """How many builds finished: a new value means a new PDF to show."""
    pdf_version: int
    """The PDF's modification time when the last build finished, 0 if none."""


def handout(deck: Path, lang: Lang) -> Path:
    """Where the deck's whole handout in `lang` is built.

    Returns:
        Its path, which may not exist yet.
    """
    settings = DeckSettings.from_yaml(deck)
    name = deck_name_from_dir(settings.paths.current_dir)
    return lang_dir(settings.paths.pdf_dir, lang) / f"{name}-handout.pdf"


def build_command(workspace: Path, lang: Lang) -> list[str]:
    """`deckz run` of a deck's whole handout, every option spelled out.

    The workspace's own deckz, and no option left to the person's `.env`.

    Returns:
        The command, to run in the deck's directory (of the workspace, or \
        of another checkout).
    """
    return [
        str(workspace / ".venv" / "bin" / "deckz"),
        "run",
        "--handout",
        "--no-presentation",
        "--no-print",
        "--no-part-handouts",
        "--no-html",
        "--no-sync",
        "--lang",
        lang,
    ]


def watch_command(workspace: Path, lang: Lang) -> list[str]:
    """`build_command`, watching.

    Returns:
        The command, to run in the deck's directory.
    """
    deckz, run, *options = build_command(workspace, lang)
    return [deckz, run, "--watch", *options]


def environment() -> dict[str, str]:
    """The environment a workspace's own deckz runs in.

    Returns:
        studioz's, without its virtual environment, and with lines wide \
        enough not to wrap.
    """
    variables = dict(os.environ)
    # studioz's own environment (the main checkout's) isn't the workspace's.
    variables.pop("VIRTUAL_ENV", None)
    # Wide enough that Rich doesn't wrap a log line.
    variables["COLUMNS"] = "400"
    variables["PYTHONUNBUFFERED"] = "1"
    return variables


def workspace_environment(workspace: Path, **extra: str) -> dict[str, str]:
    """`environment()`, with the workspace's own `.venv/bin` first on the `PATH`.

    What git's hooks run `deckz` from (they take it from the `PATH`), and
    any other command run there.

    Returns:
        The variables, `extra` added.
    """
    variables = environment()
    venv = workspace / ".venv" / "bin"
    if venv.is_dir():
        variables["PATH"] = f"{venv}{os.pathsep}{variables.get('PATH', '')}"
    return variables | extra


class Watch:
    def __init__(
        self, workspace: Path, deck: Path, lang: Lang, command: Sequence[str]
    ) -> None:
        self.workspace = workspace
        self.deck = deck
        self.lang = lang
        self.pdf = handout(deck, lang)
        self.log: deque[str] = deque(maxlen=_LOG_LINES)
        self.clients = 0
        self.unwatched_since = monotonic()
        self._lock = Lock()
        self._state = State.BUILDING
        self._errors: list[str] = []
        self._built = 0
        self._pdf_version = self._pdf_mtime()
        self._process = subprocess.Popen(
            command,
            cwd=deck,
            env=environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            # Its own process group: a Ctrl-C in studioz's terminal doesn't
            # reach it, and stopping it stops its Typst workers too.
            start_new_session=True,
        )
        assert self._process.stdout is not None
        Thread(target=self._read, args=(self._process.stdout,), daemon=True).start()

    def _pdf_mtime(self) -> int:
        try:
            return self.pdf.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _read(self, stream: IO[str]) -> None:
        for raw in stream:
            line = raw.rstrip()
            if line:
                self._parse(line)
        code = self._process.wait()
        with self._lock:
            self.log.append(f"(deckz s'est arrêté, code {code})")
            self._state = State.STOPPED

    def _parse(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            record = _RECORD.fullmatch(line)
            if record is None:
                # A message's next lines are indented.
                if line.startswith(" ") and self._errors:
                    self._errors.append(line.strip())
                return
            level, message = record["level"], record["message"]
            if level in {"ERROR", "CRITICAL"}:
                self._state = State.FAILED
                self._errors = [message]
            elif message in _STARTED:
                self._state = State.BUILDING
                self._errors = []
            elif message in _FINISHED:
                self._state = State.BUILT
                self._built += 1
                self._pdf_version = self._pdf_mtime()

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(
                self._state, tuple(self._errors), self._built, self._pdf_version
            )

    def follow(self) -> None:
        """Count a page showing this watch, which keeps it running."""
        with self._lock:
            self.clients += 1

    def unfollow(self) -> None:
        with self._lock:
            self.clients -= 1
            self.unwatched_since = monotonic()

    def alive(self) -> bool:
        return self._process.poll() is None

    def stop(self) -> None:
        """Stop the watch and its Typst workers, gently first."""
        if not self.alive():
            return
        group = os.getpgid(self._process.pid)
        self._process.send_signal(signal.SIGINT)
        try:
            self._process.wait(_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(group, signal.SIGKILL)
            self._process.wait()


class Watches:
    """The watches studioz runs, at most one per workspace."""

    def __init__(
        self,
        command: Callable[[Path, Lang], list[str]] = watch_command,
        idle_after: float = 30.0,
    ) -> None:
        self._command = command
        self._idle_after = idle_after
        self._watches: dict[Path, Watch] = {}
        self._lock = Lock()

    def watch(self, workspace: Path, deck: Path, lang: Lang) -> Watch:
        """The workspace's watch of `deck` in `lang`, started if needed.

        Returns:
            The watch, replacing any other one of the workspace.
        """
        with self._lock:
            current = self._watches.get(workspace)
            if (
                current
                and current.deck == deck
                and current.lang == lang
                and current.alive()
            ):
                return current
            if current:
                current.stop()
            started = Watch(workspace, deck, lang, self._command(workspace, lang))
            self._watches[workspace] = started
            return started

    def get(self, workspace: Path) -> Watch | None:
        return self._watches.get(workspace)

    def stop_idle(self) -> list[Watch]:
        """Stop the watches no page has followed for a while.

        Returns:
            The watches stopped.
        """
        now = monotonic()
        with self._lock:
            idle = [
                w
                for w in self._watches.values()
                if w.clients == 0 and now - w.unwatched_since > self._idle_after
            ]
            for watch in idle:
                del self._watches[watch.workspace]
        for watch in idle:
            watch.stop()
        return idle

    def stop_all(self) -> None:
        with self._lock:
            stopping = list(self._watches.values())
            self._watches.clear()
        for watch in stopping:
            watch.stop()
