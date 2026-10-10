from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.components.checks import ChecksRunner
from deckz.configuring.settings import GlobalPaths, GlobalSettings
from deckz.exceptions import HookError


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir))


def test_without_a_plugin_module_only_builtin_checks_run(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    settings = _settings(tmp_path)
    runner = ChecksRunner(settings, tmp_path / "templates" / "checks.py")

    checks = runner.checks()

    assert set(checks) == {
        "lab-ids",
        "lab-pairs",
        "lab-outputs",
        "lab-secrets",
        "lab-format",
        "asset-credits",
        "raw-latex",
        "lab-urls",
    }
    assert checks["raw-latex"]() == []


def test_plugin_checks_are_merged_in(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "templates" / "checks.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "def checks(settings):\n    return {'repo-specific': lambda: ['a problem']}\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    runner = ChecksRunner(settings, module)

    checks = runner.checks()

    assert checks["repo-specific"]() == ["a problem"]
    assert "lab-ids" in checks


def test_a_plugin_check_colliding_with_a_builtin_is_rejected(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "templates" / "checks.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "def checks(settings):\n    return {'lab-ids': lambda: []}\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    runner = ChecksRunner(settings, module)

    with raises(HookError, match="lab-ids"):
        runner.checks()


def test_a_malformed_plugin_mapping_is_rejected(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "templates" / "checks.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "def checks(settings):\n    return {'bad': 'not callable'}\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    runner = ChecksRunner(settings, module)

    with raises(HookError, match="expected a"):
        runner.checks()
