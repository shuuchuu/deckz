from os.path import relpath
from pathlib import Path
from shutil import copytree
from subprocess import run
from typing import Any

from pygit2 import init_repository
from pytest import fixture, raises

from deckz.cli import main
from deckz.configuring.settings import GlobalSettings
from deckz.setting_up import Status, deckz_checkout, incomplete, setup

_SETUP = """
setup:
  requires:
    - command: git
      why: the tests
    - command: no-such-command-deckz
      why: a missing tool
      install: apt install no-such-package
  steps:
    - name: make the marker
      run: [python3, -c, "open('marker', 'w').close()"]
      creates: marker
"""


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    (root / "user-variables.yml").unlink()
    with (root / "deckz.yml").open("a", encoding="utf8") as deckz_yml:
        deckz_yml.write(_SETUP)
    init_repository(str(root))
    monkeypatch.chdir(root)
    return root


def _by_name(repo: Path, **kwargs: Any) -> dict[str, Any]:
    return {item.name: item for item in setup(GlobalSettings.from_yaml(repo), **kwargs)}


def test_check_reports_and_changes_nothing(repo: Path) -> None:
    items = _by_name(repo, check=True)

    assert items["git"].status is Status.OK
    assert items["no-such-command-deckz"].status is Status.MISSING
    assert "apt install no-such-package" in items["no-such-command-deckz"].detail
    assert items["git hooks"].status is Status.MISSING
    assert items["make the marker"].status is Status.MISSING
    assert items["videos"].status is Status.OK
    assert not (repo / "marker").exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_setup_installs_the_hooks_and_runs_the_steps_once(repo: Path) -> None:
    first = _by_name(repo)

    assert first["git hooks"].status is Status.DONE
    assert first["make the marker"].status is Status.DONE
    assert (repo / "marker").exists()
    assert (repo / ".git" / "hooks" / "pre-commit").exists()

    second = _by_name(repo)

    assert second["git hooks"].status is Status.OK
    assert second["make the marker"].status is Status.OK
    # A tool a person must install stays missing.
    assert incomplete(second.values())


def test_a_failing_step_reports_its_output(repo: Path) -> None:
    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8").replace(
            "open('marker', 'w').close()", "raise SystemExit('broken step')"
        ),
        encoding="utf8",
    )

    item = _by_name(repo)["make the marker"]

    assert item.status is Status.FAILED
    assert "broken step" in item.detail


def test_setup_command_exits_1_while_something_is_missing(
    repo: Path, capsys: Any
) -> None:
    with raises(SystemExit) as exc_info:
        main(("setup",))

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "missing no-such-command-deckz" in output
    assert "done    git hooks" in output


def _git(cwd: Path, *args: str) -> None:
    run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@fixture
def deckz_clone(tmp_path: Path) -> tuple[Path, Path]:
    # A clone of a deckz "upstream", and a second clone pushing to it.
    upstream = tmp_path / "upstream.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(upstream))
    pusher = tmp_path / "pusher"
    _git(tmp_path, "clone", str(upstream), str(pusher))
    _git(pusher, "commit", "--allow-empty", "-m", "first")
    _git(pusher, "push", "origin", "HEAD:main")
    clone = tmp_path / "deckz"
    _git(tmp_path, "clone", str(upstream), str(clone))
    return clone, pusher


def test_an_up_to_date_deckz_checkout_is_ok(
    repo: Path, deckz_clone: tuple[Path, Path]
) -> None:
    clone, _ = deckz_clone

    item = deckz_checkout(GlobalSettings.from_yaml(repo), clone)

    assert item.status is Status.OK


def test_a_deckz_checkout_behind_its_upstream_is_missing(
    repo: Path, deckz_clone: tuple[Path, Path]
) -> None:
    clone, pusher = deckz_clone
    for message in ("fix", "another fix"):
        _git(pusher, "commit", "--allow-empty", "-m", message)
    _git(pusher, "push", "origin", "HEAD:main")

    item = deckz_checkout(GlobalSettings.from_yaml(repo), clone)

    # Seen through the fetch: the clone itself never fetched these commits.
    assert item.status is Status.MISSING
    assert "2 commits behind origin/main" in item.detail
    assert f"`git -C {relpath(clone, repo)} pull`" in item.detail


def test_a_deckz_branch_with_no_upstream_is_ok(
    repo: Path, deckz_clone: tuple[Path, Path]
) -> None:
    clone, _ = deckz_clone
    _git(clone, "switch", "--create", "topic")

    item = deckz_checkout(GlobalSettings.from_yaml(repo), clone)

    assert item.status is Status.OK
