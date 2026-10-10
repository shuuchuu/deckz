from collections.abc import Iterator
from contextlib import contextmanager, suppress
from logging import getLogger
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING

from ..models import CompileResult
from .protocols import CompilerProtocol

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess

# Every compilation runs in a child process, never in deckz's own process.
# Typst's memoization cache is global to the process that compiles and only
# ages entries out after several further compilations, so compiling several
# documents in one process adds up their memory (two ~530-page decks: 5.2GB),
# and dropping the `typst.Compiler` objects frees nothing. A child that exits
# gives everything back.
#
# Under `keep_warm()` (what `deckz run --watch` uses), each main file keeps
# its own child alive across builds instead, so Typst's incremental cache
# survives from one rebuild to the next: ~0.15s to recompile a 145-page deck
# after a one-fragment edit, against ~1s cold. Each child's memory levels off
# (entries unused for several compilations are evicted).
_warm_workers: dict[Path, "_Worker"] | None = None
_warm_lock = Lock()

# Every live worker, warm or not, so that `stop()` can kill them all; once
# stopped, no new compilation starts.
_live_workers: set["_Worker"] = set()
_live_lock = Lock()
_stopped = False

# How often a worker's memory is checked against `memory_max` while it compiles.
_MEMORY_POLL_SECONDS = 0.5
_STATUS = Path("/proc/self/status")


def _resident_memory(pid: int) -> int | None:
    """Resident memory of process `pid`, in bytes.

    Returns:
        Its `VmRSS` from Linux's `/proc`, or None elsewhere, or once the \
        process is gone.
    """
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


def _serve(
    connection: Connection,
    main: str,
    font_paths: list[str],
    ignore_system_fonts: bool,
) -> None:
    """Child process loop: compile `main` on each request, until told to stop."""
    from signal import SIG_IGN, SIGINT, signal

    # SIGINT is already blocked (see `_Worker`): make that permanent.
    signal(SIGINT, SIG_IGN)

    import typst

    compiler = typst.Compiler(
        main,
        root=str(Path(main).parent),
        font_paths=font_paths,
        ignore_system_fonts=ignore_system_fonts,
    )
    output = str(Path(main).with_suffix(".pdf"))
    # The parent going away closes the pipe: stop quietly then too.
    while _next_request(connection):
        try:
            _, warnings = compiler.compile_with_warnings(output=output)
        except typst.TypstError as e:
            connection.send((False, e.diagnostic or str(e)))
        else:
            connection.send((True, "".join(w.diagnostic for w in warnings)))
    connection.close()


def _next_request(connection: Connection) -> bool:
    try:
        return connection.recv()
    except EOFError:
        return False


@contextmanager
def _sigint_blocked() -> Iterator[None]:
    """Block SIGINT in this thread, and so in the processes it starts meanwhile.

    Ctrl-C reaches the whole process group, workers included: they must leave
    it to the parent, which stops them, rather than die with a traceback of
    their own, even while still starting up. A child inherits its parent
    thread's signal mask, and, unlike ignoring the signal, blocking it works
    from any thread, e.g. the deck builder's pool threads.
    """
    from signal import SIG_BLOCK, SIG_SETMASK, SIGINT, pthread_sigmask

    previous = pthread_sigmask(SIG_BLOCK, {SIGINT})
    try:
        yield
    finally:
        pthread_sigmask(SIG_SETMASK, previous)


class _Worker:
    def __init__(
        self,
        main: Path,
        font_paths: tuple[Path, ...],
        ignore_system_fonts: bool,
        memory_max: int | None = None,
    ) -> None:
        self._memory_max = memory_max
        self._connection, child_connection = get_context("spawn").Pipe()
        self._process: BaseProcess = get_context("spawn").Process(
            target=_serve,
            args=(
                child_connection,
                str(main),
                [str(path) for path in font_paths],
                ignore_system_fonts,
            ),
            daemon=True,
        )
        with _sigint_blocked():
            self._process.start()
        child_connection.close()
        self.lock = Lock()
        self._forget_lock = Lock()
        self._forgotten = False
        with _live_lock:
            _live_workers.add(self)
            stopped = _stopped
        if stopped:
            # `stop()` ran while this worker was starting.
            self.kill()

    def compile(self) -> CompileResult:
        try:
            self._connection.send(True)
            if self._memory_max is not None and self._over_memory_max():
                self.kill()
                return CompileResult(
                    False,
                    "the Typst worker process went over typst_memory_max "
                    f"({self._memory_max / 2**30:.1f} GiB) and was stopped: raise "
                    "the limit in deckz.yml, or build fewer outputs at once",
                )
            ok, diagnostics = self._connection.recv()
        except (EOFError, OSError):
            self.close()
            return CompileResult(
                False,
                f"the Typst worker process died (exit code {self._process.exitcode})"
                ", possibly killed for using too much memory",
            )
        return CompileResult(ok, diagnostics)

    def _over_memory_max(self) -> bool:
        """Wait for the compilation's answer, checking the worker's memory meanwhile.

        Returns:
            Whether the worker went over `memory_max` before answering.
        """
        pid, memory_max = self._process.pid, self._memory_max
        if pid is None or memory_max is None:
            return False
        while True:
            memory = _resident_memory(pid)
            if memory is not None and memory > memory_max:
                return True
            if self._connection.poll(_MEMORY_POLL_SECONDS):
                return False

    @property
    def alive(self) -> bool:
        return self._process.is_alive()

    def close(self) -> None:
        if self._process.is_alive():
            with suppress(OSError):
                self._connection.send(False)
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.kill()
        self._forget()

    def kill(self) -> None:
        """Stop at once, even mid-compilation: its `compile` then fails.

        Doesn't wait for `self.lock`: a concurrent `compile()` may be
        blocked waiting for a long Typst compilation to finish, and this
        must interrupt it immediately, not once it's done.
        """
        self._process.kill()
        self._process.join()
        self._forget()

    def _forget(self) -> None:
        # `compile()`'s own cleanup on a dead worker (`close()`) can race
        # with a concurrent `kill()` (e.g. Ctrl-C): guard against both
        # closing `_connection` (not idempotent, unlike a plain file) so
        # only the first one actually tears the worker down.
        with self._forget_lock:
            if self._forgotten:
                return
            self._forgotten = True
        with _live_lock:
            _live_workers.discard(self)
        self._connection.close()


def stop() -> None:
    """Kill every Typst worker and refuse any further compilation.

    For the CLI's Ctrl-C handling: the compilations running end at once, as \
    failures, and those not started yet fail without starting.
    """
    global _stopped
    with _live_lock:
        _stopped = True
        workers = list(_live_workers)
    for worker in workers:
        worker.kill()


@contextmanager
def keep_warm() -> Iterator[None]:
    """Keep one Typst worker process per main file alive until exiting.

    For long-lived callers that compile the same main files repeatedly -- \
    `deckz run --watch` -- so every rebuild after the first is incremental.
    """
    global _warm_workers
    with _warm_lock:
        _warm_workers = {}
    interrupted = False
    try:
        yield
    except BaseException:
        # E.g. Ctrl-C: don't wait for the compilations still running.
        interrupted = True
        raise
    finally:
        with _warm_lock:
            workers, _warm_workers = _warm_workers, None
        for worker in workers.values():
            if interrupted:
                worker.kill()
            else:
                worker.close()


class TypstCompiler(CompilerProtocol):
    """Compile a `.typ` main file to PDF with the `typst` bindings.

    Each compilation runs in a child process: a fresh one that exits right \
    after, or, inside [`keep_warm`][deckz.components.compiler.keep_warm], \
    one long-lived process per main file whose Typst cache makes rebuilds \
    incremental. At most `max_parallel` compilations run at once: Typst \
    already parallelizes a single compilation across cores, and each \
    concurrent one adds a whole document's memory (up to a few GB).

    With `memory_max` (bytes), a compilation whose process goes over it \
    is stopped and fails, instead of the machine running out of memory. \
    It's checked every half second, on Linux only (`/proc`).

    Typst finds fonts in `font_paths`, in its own embedded fonts, and, \
    unless `ignore_system_fonts`, in the system's. Scanning the system's \
    fonts costs every child process a fixed ~0.2s with a thousand fonts \
    installed, so ignoring them speeds up builds as well as making them \
    independent of the machine's fonts.
    """

    def __init__(
        self,
        max_parallel: int = 1,
        font_paths: tuple[Path, ...] = (),
        ignore_system_fonts: bool = False,
        memory_max: int | None = None,
    ) -> None:
        self._slots = BoundedSemaphore(max_parallel)
        self._font_paths = font_paths
        self._ignore_system_fonts = ignore_system_fonts
        self._memory_max = memory_max
        if memory_max is not None and not _STATUS.exists():
            getLogger(__name__).warning(
                "typst_memory_max is ignored: it needs Linux's /proc"
            )

    def _worker(self, main: Path) -> _Worker:
        return _Worker(
            main, self._font_paths, self._ignore_system_fonts, self._memory_max
        )

    def compile(self, file: Path) -> CompileResult:
        main = file.resolve()
        with self._slots:
            if _stopped:
                return CompileResult(False, "compilation cancelled")
            with _warm_lock:
                workers = _warm_workers
                if workers is not None and (
                    main not in workers or not workers[main].alive
                ):
                    workers[main] = self._worker(main)
                worker = workers[main] if workers is not None else None
            if worker is not None:
                with worker.lock:
                    return worker.compile()
            worker = self._worker(main)
            try:
                return worker.compile()
            finally:
                worker.close()
