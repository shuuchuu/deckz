"""The work the checks of one run share, each piece computed once.

`deckz check`, and every caller of `ChecksRunner.findings`, runs its checks
inside `shared_run()`. In it, a function decorated with `shared` computes its
result once for given arguments, and hands that same object to every later
caller: each check used to list the repository's files, find its decks, read
its notebooks and parse its decks again. The shared functions call each other
(the parsed decks need the decks' settings, which need the configuration
files): a graph of preprocessing steps, each computed on demand, so a run that
names one check, or a hook passing a few `paths`, computes only what its checks
ask for.

Nothing outlives the run. Outside one, a shared function computes on every
call, as it did before, so a long process (`deckz run --watch`, studioz's
server) never gets a stale result. A shared result is read-only: a caller that
needs to change it changes a copy.

A run is thread-safe: `in_run` hands it to a thread, and two threads asking for
the same result wait for one computation. Resources the run opens on demand (a
process pool) close when it ends (`run_resource`).
"""

from collections.abc import Callable, Generator, Hashable
from concurrent.futures import Future
from contextlib import AbstractContextManager, ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Lock
from typing import Any


class _Run:
    def __init__(self) -> None:
        self.lock = Lock()
        self.results: dict[Hashable, Future[Any]] = {}
        self.resources = ExitStack()


_RUN: ContextVar[_Run | None] = ContextVar("deckz_shared_run", default=None)


@contextmanager
def shared_run() -> Generator[None]:
    """Share the work of the `shared` functions until the block ends.

    Nested in another run, it is that run: what it computed stays shared.

    Yields:
        Nothing.
    """
    if _RUN.get() is not None:
        yield
        return
    run = _Run()
    token = _RUN.set(run)
    try:
        with run.resources:
            yield
    finally:
        _RUN.reset(token)


def in_run[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """`function`, called in the current run wherever it's called from.

    A thread doesn't inherit the context of the one that starts it: a
    function submitted to a thread pool goes through this.

    Returns:
        A function calling `function` in a copy of the current context.
    """
    context = copy_context()

    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        # A context can't be entered by two threads at once: one copy per call.
        return context.copy().run(function, *args, **kwargs)

    return call


def shared[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Compute `function` once per arguments in a run, on every call outside one.

    Its arguments must be hashable. A call that raises shares its exception:
    the run's later calls raise it too.

    Returns:
        The decorated function.
    """

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        run = _RUN.get()
        if run is None:
            return function(*args, **kwargs)
        key = (
            function.__module__,
            function.__qualname__,
            args,
            tuple(sorted(kwargs.items())),
        )
        with run.lock:
            future = run.results.get(key)
            computes = future is None
            if future is None:
                future = run.results[key] = Future()
        if computes:
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as error:
                future.set_exception(error)
                raise
        return future.result()

    return wrapper


def run_resource[T](key: Hashable, open_: Callable[[], AbstractContextManager[T]]) -> T:
    """A resource opened once in the run, closed when it ends.

    Args:
        key: What names the resource in the run.
        open_: Opens it, as a context manager (e.g. a process pool).

    Returns:
        The resource.

    Raises:
        RuntimeError: Outside a run, where nothing would close it.
    """
    run = _RUN.get()
    if run is None:
        msg = "run_resource needs a shared_run()"
        raise RuntimeError(msg)
    with run.lock:
        future = run.results.get(("resource", key))
        if future is None:
            future = run.results["resource", key] = Future()
            future.set_result(run.resources.enter_context(open_()))
    return future.result()


def in_shared_run() -> bool:
    """Whether a `shared_run()` is active here.

    Returns:
        True in a run.
    """
    return _RUN.get() is not None
