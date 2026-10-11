from os import environ
from pathlib import Path
from typing import Any

import appdirs
from pytest import fixture


@fixture(autouse=True)
def _isolated_user_config_dir(tmp_path: Path, monkeypatch: Any) -> None:
    # Never read or write the developer's own ~/.config/deckz. Tests needing
    # specific user config patch this again with their own directory.
    user_dir = tmp_path / "isolated-user-config"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))


@fixture(autouse=True)
def _isolated_environment(monkeypatch: Any, tmp_path_factory: Any) -> None:
    # Neither the developer's own DECKZ_* defaults (e.g. DECKZ_LANG) nor a
    # .env file above the test's directory or in their deckz config
    # directory may change what a command does.
    for name in [name for name in environ if name.startswith("DECKZ_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("dotenv.find_dotenv", lambda *_, **__: "")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@fixture(autouse=True)
def _isolated_git(monkeypatch: Any, tmp_path_factory: Any) -> None:
    # A git hook (deckz's pre-commit runs the tests) exports GIT_DIR,
    # GIT_INDEX_FILE and the like. A test's own `git` calls would follow them
    # into the real repository instead of the test's temporary one: once, from
    # a linked worktree, they committed fixtures onto the branch and set
    # core.bare and test remotes in the shared config.
    for name in [name for name in environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    # Nor may the developer's own git configuration, and the code under test
    # commits (`labs publish`'s commit-tree): CI's container has no identity,
    # and git can't make one up from its hostname.
    config = tmp_path_factory.mktemp("git") / "config"
    config.write_text(
        "[user]\n\tname = test\n\temail = test@example.com\n\tuseConfigOnly = true\n",
        encoding="utf8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
