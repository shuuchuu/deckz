import subprocess
from os import environ
from pathlib import Path
from typing import Any

import appdirs
from fastapi.testclient import TestClient
from pytest import fixture
from studioz.app import create_app


@fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: Any, tmp_path_factory: Any) -> None:
    # As in deckz's tests: neither the developer's configuration nor a git
    # hook's GIT_* variables (deckz's pre-commit runs the tests) may reach
    # the test's repository.
    user_dir = tmp_path / "isolated-user-config"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    for name in [n for n in environ if n.startswith(("DECKZ_", "GIT_"))]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=test",
            "-c",
            "user.email=t@e.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@fixture
def repository(tmp_path: Path) -> Path:
    main = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(main))
    (main / ".gitignore").write_text("/.run/\n", encoding="utf8")
    (main / "deckz.yml").write_text("{}\n", encoding="utf8")
    deck = main / "client" / "abc"
    deck.mkdir(parents=True)
    (deck / "deck.yml").write_text("name: abc\n", encoding="utf8")
    _git(main, "add", "-A")
    _git(main, "commit", "-m", "Initial")
    return main


@fixture
def client(repository: Path) -> TestClient:
    return TestClient(create_app(repository), base_url="http://localhost:8421")
