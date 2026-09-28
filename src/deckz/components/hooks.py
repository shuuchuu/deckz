"""Load the Python hooks a deckz-managed repository supplies.

Two modules of the target repository are executed by deckz:

- `templates/jinja2/env.py`, defining \
    `environment_for(suffix: str) -> jinja2.Environment` (see \
    [`Renderer`][deckz.components.renderer.Renderer]);
- `templates/assets_builders.py`, defining \
    `assets_builders(assets_dir: Path, compiler: CompilerProtocol) -> \
    Iterable[AssetsBuilderProtocol]` (see \
    [`AssetsBuilder`][deckz.components.assets_builder.AssetsBuilder]).

This is a trust boundary: loading a hook runs arbitrary code from the \
repository, with the user's permissions, so deckz must only be run on \
repositories one trusts, like any build script.

A hook module may declare `DECKZ_HOOKS_VERSION = 1`, the version of this \
contract it was written against. Leaving it out means version 1. A later, \
incompatible contract will bump the version so that a hook written against \
another one fails to load with a clear message instead of misbehaving.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..exceptions import DeckzError, HookError
from ..utils import import_module_from_path

HOOKS_VERSION = 1
"""The version of the hook contract this deckz implements."""


def load_hook(path: Path, module_name: str, function_name: str) -> Callable[..., Any]:
    """Import a hook module and return its hook function.

    Args:
        path: Path of the module's `.py` file.
        module_name: Name to register the module under.
        function_name: Name of the function the module must define.

    Returns:
        The hook function.

    Raises:
        DeckzError: If `path` doesn't exist or isn't a Python module.
        HookError: If the module fails to import, targets another contract \
            version or doesn't define `function_name` as a function.
    """
    try:
        module = import_module_from_path(path, module_name)
    except DeckzError:
        raise
    except Exception as e:
        # The module is the repository's own code: it can raise anything.
        msg = f"{path} failed to load: {e!r}"
        raise HookError(msg) from e
    version = getattr(module, "DECKZ_HOOKS_VERSION", HOOKS_VERSION)
    if version != HOOKS_VERSION:
        msg = (
            f"{path} targets deckz hooks version {version!r}, this deckz supports "
            f"version {HOOKS_VERSION}"
        )
        raise HookError(msg)
    function = getattr(module, function_name, None)
    if not callable(function):
        msg = f"{path} must define a `{function_name}` function"
        raise HookError(msg)
    return function
