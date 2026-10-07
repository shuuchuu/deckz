from collections.abc import Callable, Mapping
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from ..exceptions import HookError
from .hooks import load_hook
from .protocols import ChecksRunnerProtocol

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings


class ChecksRunner(ChecksRunnerProtocol):
    """Merge deckz's own content checks with a target repo's own ones.

    `deckz` has a few generic content checks of its own (see
    [`content_checks`][deckz.analyzing.content_checks]). A target repo can
    add its own, theme- or content-specific ones (e.g. a lab frame pattern)
    from a Python module, by convention `templates/checks.py` (see
    `GlobalPaths.checks_module`), exposing:

        def checks(
            settings: GlobalSettings
        ) -> Mapping[str, Callable[[], list[str]]]: ...

    called once, with the repository's own settings, to obtain every extra
    check to run, each returning its problems the same way deckz's built-in
    ones do. See [`hooks`][deckz.components.hooks] for the contract's
    versioning and trust boundary. The module is optional: a repo with
    nothing of its own simply doesn't have one.
    """

    def __init__(self, settings: "GlobalSettings", checks_module: Path) -> None:
        self._settings = settings
        self._checks_module_path = checks_module

    def checks(self) -> Mapping[str, Callable[[], list[str]]]:
        from ..analyzing.content_checks import CHECKS

        settings = self._settings
        builtin: dict[str, Callable[[], list[str]]] = {
            name: (lambda settings=settings, check=check: check(settings))
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
