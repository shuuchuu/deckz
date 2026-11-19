import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from functools import cached_property
from inspect import signature
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..exceptions import HookError
from ..run_cache import in_run, shared_run
from .hooks import load_hook
from .protocols import ChecksRunnerProtocol

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings


_LEADING_PATH = re.compile(r"(?P<path>[^\s:]+?)(?::\d+)?(?=[:\s]|$)")


@dataclass(frozen=True)
class Finding:
    """A problem a check reported, with where it applies."""

    check: str
    text: str
    """The problem, as the check wrote it."""
    blocking: bool
    """Whether it blocks a commit (`ChecksSettings.blocking`)."""

    @property
    def path(self) -> PurePosixPath | None:
        """The repository path the problem starts with, if any.

        Every built-in check starts its problems with the file they're
        about (`path: …`, `path:line: …`, a notebook pair's stem), as
        plugins are asked to: that's what ties a problem to the decks or
        notebooks a publication sends.
        """
        match = _LEADING_PATH.match(self.text)
        return PurePosixPath(match["path"]) if match else None

    def under(self, directory: PurePosixPath) -> bool:
        """Whether it's about `directory` (repository-relative) or what's in it.

        Returns:
            True if its path is `directory` or under it.
        """
        path = self.path
        return path is not None and path.is_relative_to(directory)


def run_check(
    check: Callable[..., list[str]], paths: Collection[Path] | None = None
) -> list[str]:
    """Run `check`, on `paths` if it takes them, else on the whole repository.

    Returns:
        Its problems.
    """
    if paths is None or "paths" not in signature(check).parameters:
        return check()
    return check(paths=paths)


@dataclass(frozen=True)
class CheckTiming:
    """What one check cost (`deckz check --timings`)."""

    cpu: float
    """Seconds of CPU: deckz's process and the subprocesses it waited for \
    (process pools, ruff, a type checker)."""
    wall: float
    """Seconds of wall-clock time."""


def run_checks(
    checks: Mapping[str, Callable[..., list[str]]],
    jobs: Mapping[str, Collection[Path] | None],
    *,
    in_thread: Collection[str] = (),
    timings: dict[str, CheckTiming] | None = None,
) -> dict[str, list[str]]:
    """Run checks, sharing the work they have in common, and gather their problems.

    The checks run in one `shared_run` (`deckz.run_cache`): what one of them
    lists, reads or parses, the next gets as is. Those of `in_thread` (checks
    waiting on a subprocess, e.g. a type checker: `checks.in_thread`) run in
    threads meanwhile, the others one after the other: Python checks would
    only contend for the GIL.

    Args:
        checks: Every check, by name (`ChecksRunner.checks`).
        jobs: The checks to run, in order, each with the paths it's limited \
            to (None for the whole repository; see `run_check`).
        in_thread: Checks to run in threads, alongside the others.
        timings: Filled with each check's cost, if given: the checks then \
            all run one after the other, so that each one's CPU time is its own.

    Returns:
        Each check's problems, in `jobs`' order.
    """
    from concurrent.futures import Future, ThreadPoolExecutor

    if timings is not None:
        return _timed_run(checks, jobs, timings)
    with shared_run():
        threaded = [name for name in jobs if name in in_thread]
        if not threaded:
            return {
                name: run_check(checks[name], paths) for name, paths in jobs.items()
            }
        with ThreadPoolExecutor(len(threaded)) as pool:
            futures: dict[str, Future[list[str]]] = {
                name: pool.submit(in_run(run_check), checks[name], jobs[name])
                for name in threaded
            }
            found = {
                name: run_check(checks[name], paths)
                for name, paths in jobs.items()
                if name not in futures
            }
            found |= {name: future.result() for name, future in futures.items()}
        return {name: found[name] for name in jobs}


SHARED_POOL_TIMING = "(shared process pool)"
"""The `--timings` row of the run's process pool: its processes' CPU time, \
counted once they end, with the run, whichever checks used them."""


def _timed_run(
    checks: Mapping[str, Callable[..., list[str]]],
    jobs: Mapping[str, Collection[Path] | None],
    timings: dict[str, CheckTiming],
) -> dict[str, list[str]]:
    from time import perf_counter

    with shared_run():
        found = {}
        for name, paths in jobs.items():
            cpu_start, wall_start = _cpu(), perf_counter()
            found[name] = run_check(checks[name], paths)
            timings[name] = CheckTiming(_cpu() - cpu_start, perf_counter() - wall_start)
        cpu_start, wall_start = _cpu(), perf_counter()
    # The run's pool ends with it: only then do its processes' CPU time count.
    if (cpu := _cpu() - cpu_start) >= 0.01:
        timings[SHARED_POOL_TIMING] = CheckTiming(cpu, perf_counter() - wall_start)
    return found


def _cpu() -> float:
    # deckz's CPU time, and that of its subprocesses which have ended.
    from resource import RUSAGE_CHILDREN, getrusage
    from time import process_time

    children = getrusage(RUSAGE_CHILDREN)
    return process_time() + children.ru_utime + children.ru_stime


class ChecksRunner(ChecksRunnerProtocol):
    """Merge deckz's own content checks with a target repo's own ones.

    `deckz` has a few generic content checks of its own (see
    [`content_checks`][deckz.analyzing.content_checks]). A target repo can
    add its own, theme- or content-specific ones (e.g. a lab frame pattern)
    from a Python module, by convention `templates/checks.py` (see
    `GlobalPaths.checks_module`), exposing:

        def checks(
            settings: GlobalSettings
        ) -> Mapping[str, Callable[..., list[str]]]: ...

    called once, with the repository's own settings, to obtain every extra
    check to run, each returning its problems the same way deckz's built-in
    ones do. A check may take a `paths` keyword argument (absolute paths, or
    None for the whole repository), as the built-in ones do: given files, it
    reports only about them, and returns at once when none is of a kind it
    reads. A check without one always checks the whole repository. See
    [`hooks`][deckz.components.hooks] for the contract's
    versioning and trust boundary. The module is optional: a repo with
    nothing of its own simply doesn't have one.
    """

    def __init__(self, settings: "GlobalSettings", checks_module: Path) -> None:
        self._settings = settings
        self._checks_module_path = checks_module

    def checks(self) -> Mapping[str, Callable[..., list[str]]]:
        from ..analyzing.content_checks import CHECKS

        settings = self._settings
        builtin: dict[str, Callable[..., list[str]]] = {
            name: (
                lambda paths=None, settings=settings, check=check: check(
                    settings, paths
                )
            )
            for name, check in CHECKS.items()
        }
        plugin = self._plugin_checks
        if overlap := set(builtin) & set(plugin):
            msg = (
                f"{self._checks_module_path}: checks {sorted(overlap)} already "
                "exist as a deckz built-in check"
            )
            raise HookError(msg)
        return {**builtin, **plugin}

    def findings(
        self,
        names: Collection[str] | None = None,
        paths: Collection[Path] | None = None,
    ) -> list[Finding]:
        """Run the checks `deckz check` runs, or `names`, and gather their problems.

        Args:
            names: The checks to run; None for those `deckz check` runs.
            paths: The files (absolute) the checks taking `paths` are limited \
                to; None for the whole repository.

        Returns:
            Every problem, check by check, in `checks()`'s order.
        """
        settings = self._settings
        checks = self.checks()
        found = run_checks(
            checks,
            {
                name: paths
                for name in checks
                if (
                    name in names
                    if names is not None
                    else settings.checks.runs_unnamed(name)
                )
            },
            in_thread=settings.checks.in_thread,
        )
        return [
            Finding(name, problem, settings.checks.blocking(name))
            for name, problems in found.items()
            for problem in problems
        ]

    @cached_property
    def _plugin_checks(self) -> dict[str, Callable[[], list[str]]]:
        path = self._checks_module_path
        if not path.is_file():
            return {}
        hook = load_hook(path, "deckz._checks", "checks")
        checks = dict(hook(self._settings))
        for name, check in checks.items():
            if not isinstance(name, str) or not callable(check):
                msg = (
                    f"{path}: checks returned {checks!r}, expected a "
                    "{str: callable} mapping"
                )
                raise HookError(msg)
        return checks
