import sys
from pathlib import Path

import pytest

from deckz.utils import import_module_and_submodules


def test_imports_nested_submodules_named_like_top_level_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A subpackage named like an installed module (`json` here, `matplotlib` in a
    # repo's plots) is imported as part of the package, never as that module.
    package = tmp_path / "pkg_under_test"
    (package / "json" / "deep").mkdir(parents=True)
    for init in ("", "json", "json/deep"):
        (package / init / "__init__.py").write_text("")
    (package / "json" / "deep" / "leaf.py").write_text("LOADED = True\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    before = {name for name in sys.modules if name.startswith("pkg_under_test")}
    try:
        import_module_and_submodules("pkg_under_test")
        assert sys.modules["pkg_under_test.json.deep.leaf"].LOADED
        assert "pkg_under_test.json" in sys.modules
    finally:
        for name in set(sys.modules) - before:
            if name.startswith("pkg_under_test"):
                del sys.modules[name]
