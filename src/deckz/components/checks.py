import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from functools import cached_property
from inspect import signature
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..exceptions import HookError
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
        return [
            Finding(name, problem, settings.checks.blocking(name))
            for name, check in self.checks().items()
            if (
                name in names
                if names is not None
                else settings.checks.runs_unnamed(name)
            )
            for problem in run_check(check, paths)
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
