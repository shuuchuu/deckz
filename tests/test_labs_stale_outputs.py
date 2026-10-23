import json
import subprocess
from pathlib import Path
from typing import Any

from pytest import fixture, raises

from deckz.cli import main
from deckz.configuring.settings import GlobalPaths, GlobalSettings
from deckz.exceptions import DeckzError
from deckz.labs import stale_outputs
from deckz.labs.stale_outputs import mark_current, stale_demos
from deckz.status import labs_section

DEMO = "labs/notebooks/nn/cnn/demo-fr.ipynb"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    _git(tmp_path, "init", "--quiet", "-b", "main")
    # `mark-current` commits with the user's identity.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    return tmp_path


def _settings(repo: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=repo, git_dir=repo))


def _write(repo: Path, code: str, output: str | None, path: str = DEMO) -> None:
    cell: dict[str, Any] = {
        "cell_type": "code",
        "metadata": {},
        "source": code.splitlines(keepends=True),
        "execution_count": 1 if output else None,
        "outputs": (
            [{"output_type": "stream", "name": "stdout", "text": [output]}]
            if output
            else []
        ),
    }
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"cells": [cell], "metadata": {}, "nbformat": 4}))


def _commit(repo: Path, subject: str, body: str = "") -> str:
    _git(repo, "add", "-A")
    message = f"{subject}\n\n{body}" if body else subject
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _stale(repo: Path) -> dict[str, Any]:
    return {
        str(demo.path): (
            demo.since,
            [c.subject for c in demo.commits],
            demo.uncommitted,
        )
        for demo in stale_demos(_settings(repo))
    }


def test_a_code_change_after_the_outputs_makes_a_demo_stale(repo: Path) -> None:
    _write(repo, "print(1)\n", None)
    _commit(repo, "Add the demo")
    _write(repo, "print(1)\n", "1\n")
    written = _commit(repo, "Write its outputs")
    _write(repo, "print(2)\n", "1\n")
    _commit(repo, "Print 2 instead")

    assert _stale(repo) == {DEMO: (written, ["Print 2 instead"], False)}


def test_outputs_written_again_after_the_change_are_current(repo: Path) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "print(2)\n", "1\n")
    _commit(repo, "Print 2 instead")
    _write(repo, "print(2)\n", "2\n")
    _commit(repo, "Write its outputs again")

    assert _stale(repo) == {}


def test_comments_and_blank_lines_dont_count(repo: Path) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "# Say one.\n\nprint(1)  \n", "1\n")
    _commit(repo, "Comment it")

    assert _stale(repo) == {}


def test_a_working_tree_change_counts_and_outputs_written_there_settle_it(
    repo: Path,
) -> None:
    _write(repo, "print(1)\n", "1\n")
    written = _commit(repo, "Add the demo")
    _write(repo, "print(2)\n", "1\n")

    assert _stale(repo) == {DEMO: (written, [], True)}

    _write(repo, "print(2)\n", "2\n")
    assert _stale(repo) == {}


def test_hands_on_notebooks_and_demos_never_run_are_left_out(repo: Path) -> None:
    hands_on = "labs/notebooks/nn/cnn/hands-on-fr.ipynb"
    _write(repo, "print(1)\n", "1\n", hands_on)
    _write(repo, "print(1)\n", None)
    _commit(repo, "Add the lab")
    _write(repo, "print(2)\n", "1\n", hands_on)
    _write(repo, "print(2)\n", None)
    _commit(repo, "Change both")

    assert _stale(repo) == {}


def test_mark_current_settles_a_stale_demo(repo: Path) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "print( 1 )\n", "1\n")
    _commit(repo, "Space it")

    sha, settled = mark_current(_settings(repo), [repo / DEMO], "only spacing")

    assert [str(demo.path) for demo in settled] == [DEMO]
    assert _stale(repo) == {}
    message = _git(repo, "log", "-1", "--format=%B")
    assert message.endswith(f"only spacing\n\nLab-outputs-current: {DEMO}")
    assert _git(repo, "rev-parse", "HEAD") == sha
    # A later change counts again.
    _write(repo, "print(3)\n", "1\n")
    _commit(repo, "Print 3")
    assert _stale(repo) == {DEMO: (sha, ["Print 3"], False)}


def test_a_commit_can_carry_the_trailer_itself(repo: Path) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "print( 1 )\n", "1\n")
    _commit(repo, "Space it", f"Only spacing.\n\nLab-outputs-current: {DEMO}")

    assert _stale(repo) == {}


def test_mark_current_refuses_what_it_cant_settle(repo: Path) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    settings = _settings(repo)

    with raises(DeckzError, match="its outputs are current"):
        mark_current(settings, [repo / DEMO], "why")
    _write(repo, "print(2)\n", "1\n")
    with raises(DeckzError, match="commit it first"):
        mark_current(settings, [repo / DEMO], "why")
    with raises(DeckzError, match="--reason"):
        mark_current(settings, [repo / DEMO], " ")


def test_each_blob_is_parsed_once_across_runs(repo: Path, monkeypatch: Any) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "print(2)\n", "1\n")
    _commit(repo, "Print 2 instead")
    first = _stale(repo)

    def fail(_: bytes) -> None:
        raise AssertionError

    monkeypatch.setattr(stale_outputs, "_digests", fail)
    assert _stale(repo) == first
    assert (repo / ".run" / "lab-outputs.json").is_file()


def test_labs_stale_lists_them_and_exits_1(
    repo: Path, capsys: Any, monkeypatch: Any
) -> None:
    _write(repo, "print(1)\n", "1\n")
    _commit(repo, "Add the demo")
    _write(repo, "print(2)\n", "1\n")
    _commit(repo, "Print 2 instead")
    monkeypatch.chdir(repo)

    with raises(SystemExit) as exited:
        main(("labs", "stale", "--json"))

    assert exited.value.code == 1
    (found,) = json.loads(capsys.readouterr().out)["stale"]
    assert (found["path"], found["uncommitted"]) == (DEMO, False)
    assert [c["subject"] for c in found["commits"]] == ["Print 2 instead"]


def test_status_lists_your_stale_demos_and_counts_the_others(repo: Path) -> None:
    other = "labs/notebooks/nn/rnn/demo-fr.ipynb"
    _write(repo, "print(1)\n", "1\n")
    _write(repo, "print(1)\n", "1\n", other)
    _commit(repo, "Add the demos")
    _write(repo, "print(2)\n", "1\n")
    _write(repo, "print(2)\n", "1\n", other)
    _commit(repo, "Print 2 instead")
    _git(repo, "remote", "add", "labs", str(repo / "labs.git"))

    section = labs_section(_settings(repo), set(), fetch=False, changed={DEMO})

    assert [item.text for item in section.items] == [
        f"{DEMO}: code changed since its outputs were written (1 commit)",
        "1 other demo in the repository whose code changed since their outputs "
        "were written",
    ]
