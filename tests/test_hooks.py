from pathlib import Path
from typing import TYPE_CHECKING, cast

from pytest import raises

from deckz.components.assets_builder import AssetsBuilder
from deckz.components.hooks import load_hook
from deckz.components.renderer import Renderer
from deckz.exceptions import HookError

if TYPE_CHECKING:
    from deckz.components.protocols import CompilerProtocol, GlobalFactoryProtocol


def _module(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "hook.py"
    path.write_text(source, encoding="utf8")
    return path


def test_load_hook_returns_the_function(tmp_path: Path) -> None:
    path = _module(tmp_path, "def hook(x):\n    return x + 1\n")
    assert load_hook(path, "deckz._test_hook_ok", "hook")(1) == 2


def test_load_hook_rejects_a_missing_function(tmp_path: Path) -> None:
    path = _module(tmp_path, "hook = 1\n")
    with raises(HookError, match="must define a `hook` function"):
        load_hook(path, "deckz._test_hook_missing", "hook")


def test_load_hook_reports_an_import_failure(tmp_path: Path) -> None:
    path = _module(tmp_path, "import no_such_module_anywhere\n")
    with raises(HookError, match=r"failed to load.*no_such_module_anywhere"):
        load_hook(path, "deckz._test_hook_broken", "hook")


def test_load_hook_rejects_another_contract_version(tmp_path: Path) -> None:
    path = _module(tmp_path, "DECKZ_HOOKS_VERSION = 2\ndef hook():\n    pass\n")
    with raises(HookError, match="version 2"):
        load_hook(path, "deckz._test_hook_version", "hook")


def test_renderer_rejects_a_non_environment(tmp_path: Path) -> None:
    path = _module(tmp_path, "def environment_for(suffix):\n    return None\n")
    renderer = Renderer(path, cast("GlobalFactoryProtocol", None))
    with raises(HookError, match=r"not a jinja2\.Environment"):
        renderer.environment_for(".md")


def test_assets_builder_rejects_a_malformed_builder(tmp_path: Path) -> None:
    path = _module(
        tmp_path, "def assets_builders(assets_dir, compiler):\n    return [object()]\n"
    )
    builder = AssetsBuilder(path, tmp_path, cast("CompilerProtocol", None))
    with raises(HookError, match="lacks a build_assets or watched_dirs"):
        builder.build_assets()
