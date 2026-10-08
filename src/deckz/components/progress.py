from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from .protocols import ProgressReporterProtocol


class NullProgress(ProgressReporterProtocol):
    """Report nothing: the default when no one shows progress (tests, scripts)."""

    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        yield lambda: None


class PrefixedProgress(ProgressReporterProtocol):
    """Report through `progress`, each task's description starting with `prefix`."""

    def __init__(self, progress: ProgressReporterProtocol, prefix: str) -> None:
        self._progress = progress
        self._prefix = prefix

    def track(
        self, description: str, total: int
    ) -> AbstractContextManager[Callable[[], None]]:
        return self._progress.track(f"{self._prefix}{description}", total)
