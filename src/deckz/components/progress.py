from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .protocols import ProgressReporterProtocol


class NullProgress(ProgressReporterProtocol):
    """Report nothing: the default when no one shows progress (tests, scripts)."""

    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        yield lambda: None
