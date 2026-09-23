from collections.abc import Iterator
from contextlib import contextmanager, suppress
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


def _serve(connection: Connection, main: str) -> None:
    """Child process loop: compile `main` on each request, until told to stop."""
    import typst

    compiler = typst.Compiler(main, root=str(Path(main).parent))
    output = str(Path(main).with_suffix(".pdf"))
    while connection.recv():
        try:
            _, warnings = compiler.compile_with_warnings(output=output)
        except typst.TypstError as e:
            connection.send((False, e.diagnostic or str(e)))
        else:
            connection.send((True, "".join(w.diagnostic for w in warnings)))
    connection.close()


class _Worker:
    def __init__(self, main: Path) -> None:
        self._connection, child_connection = get_context("spawn").Pipe()
        self._process: BaseProcess = get_context("spawn").Process(
            target=_serve, args=(child_connection, str(main)), daemon=True
        )
        self._process.start()
        child_connection.close()
        self.lock = Lock()

    def compile(self) -> CompileResult:
        try:
            self._connection.send(True)
            ok, diagnostics = self._connection.recv()
        except (EOFError, OSError):
            self.close()
            return CompileResult(
                False,
                "",
                f"the Typst worker process died (exit code {self._process.exitcode})"
                ", possibly killed for using too much memory",
            )
        return CompileResult(ok, "", diagnostics)

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
        self._connection.close()


@contextmanager
def keep_warm() -> Iterator[None]:
    """Keep one Typst worker process per main file alive until exiting.

    For long-lived callers that compile the same main files repeatedly -- \
    `deckz run --watch` -- so every rebuild after the first is incremental.
    """
    global _warm_workers
    with _warm_lock:
        _warm_workers = {}
    try:
        yield
    finally:
        with _warm_lock:
            workers, _warm_workers = _warm_workers, None
        for worker in workers.values():
            worker.close()


class TypstCompiler(CompilerProtocol):
    """Compile a `.typ` main file to PDF with the `typst` bindings.

    Each compilation runs in a child process: a fresh one that exits right \
    after, or, inside [`keep_warm`][deckz.components.typst_compiler.keep_warm], \
    one long-lived process per main file whose Typst cache makes rebuilds \
    incremental. At most `max_parallel` compilations run at once: Typst \
    already parallelizes a single compilation across cores, and each \
    concurrent one adds a whole document's memory (up to a few GB).
    """

    def __init__(self, max_parallel: int = 1) -> None:
        self._slots = BoundedSemaphore(max_parallel)

    def compile(self, file: Path) -> CompileResult:
        main = file.resolve()
        with self._slots:
            with _warm_lock:
                workers = _warm_workers
                if workers is not None and (
                    main not in workers or not workers[main].alive
                ):
                    workers[main] = _Worker(main)
                worker = workers[main] if workers is not None else None
            if worker is not None:
                with worker.lock:
                    return worker.compile()
            worker = _Worker(main)
            try:
                return worker.compile()
            finally:
                worker.close()
