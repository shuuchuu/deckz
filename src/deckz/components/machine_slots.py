"""A machine-wide limit on concurrent compilations, shared by every deckz process.

`typst_parallel_compilations` bounds one deckz process, but two processes (two
checkouts' builds, a person's `--watch` next to an agent's build) each believe
they own the machine, and memory runs out before CPU does: a large deck's
compilation takes about 2 GB. `MachineSlots(n)` holds one of `n` slot files,
locked with `flock`, for the duration of a compilation. The kernel releases a
lock when its process exits, however it exits, so a crash leaves no slot taken.

The slot files live in `$XDG_RUNTIME_DIR/deckz/compilation-slots` (else under
the temporary directory): not in the cache directory, which a sandbox may
redirect into each checkout. A process that can't create them (a sandbox's
read-only file system) opens the existing ones read-only, which `flock`
allows; with none to open, it warns and compiles without the limit.
"""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from logging import getLogger
from pathlib import Path
from tempfile import gettempdir
from time import sleep

_POLL_SECONDS = 0.2


def default_directory() -> Path:
    """Where the slot files live, the same for every deckz process of this user.

    Returns:
        `$XDG_RUNTIME_DIR/deckz/compilation-slots`, else \
        `<temporary directory>/deckz-<uid>/compilation-slots`.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = (
        Path(runtime) / "deckz"
        if runtime
        else Path(gettempdir()) / f"deckz-{os.getuid()}"
    )
    return base / "compilation-slots"


class MachineSlots:
    """At most `count` holders at once across every process using `directory`."""

    def __init__(self, count: int, directory: Path | None = None) -> None:
        self._count = count
        self._directory = directory or default_directory()
        self._logger = getLogger(__name__)

    @contextmanager
    def hold(self, cancelled: Callable[[], bool] = lambda: False) -> Iterator[bool]:
        """Hold a slot until exiting, waiting for one if they're all taken.

        Args:
            cancelled: Checked while waiting: once true, stop waiting.

        Yields:
            True while holding a slot (or when slots can't be used at all), \
            False if `cancelled` stopped the wait.
        """
        import fcntl

        descriptors = self._open()
        if not descriptors:
            yield True
            return
        held = None
        waited = False
        try:
            while held is None:
                for descriptor in descriptors:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    held = descriptor
                    break
                else:
                    if cancelled():
                        break
                    if not waited:
                        self._logger.info(
                            "Waiting for one of the %d compilation slots other "
                            "deckz processes hold (typst_machine_compilations)",
                            self._count,
                        )
                        waited = True
                    sleep(_POLL_SECONDS)
            yield held is not None
        finally:
            for descriptor in descriptors:
                # Closing a descriptor releases its lock.
                os.close(descriptor)

    def _open(self) -> list[int]:
        descriptors = []
        with suppress(OSError):
            self._directory.mkdir(parents=True, exist_ok=True)
        for index in range(self._count):
            path = self._directory / f"slot-{index}"
            try:
                descriptors.append(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
            except OSError:
                try:
                    descriptors.append(os.open(path, os.O_RDONLY))
                except OSError:
                    continue
        if not descriptors:
            self._logger.warning(
                "typst_machine_compilations is ignored: can't open or create "
                "the slot files in %s",
                self._directory,
            )
        return descriptors
