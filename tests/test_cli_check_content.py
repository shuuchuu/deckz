import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, fixture, raises

from deckz.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Iterator[Path]:
    import appdirs

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_check_content_passes_on_a_clean_repo(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    main(("check", "content"))

    assert capsys.readouterr().out == ""


def test_bare_check_runs_content_by_default(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check",))  # Should not raise: raw-latex is deferred.

    out = capsys.readouterr().out
    assert "#### raw-latex (deferred: doesn't block a commit)" in out
    assert "notes.tex" in out


def test_check_content_plain_reports_a_problem(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check", "content", "--plain"))

    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("deferred\traw-latex\tcontent/topic/notes.tex: ")


def test_check_content_fails_on_a_blocking_check(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "deck" / "deck.yml", "name: deck\nparts: [{sections: [gone]}]\n")
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    with raises(SystemExit) as exc_info:
        main(("check", "content", "--json"))

    assert exc_info.value.code == 1
    found = json.loads(capsys.readouterr().out)
    assert list(found["blocking"]) == ["deck-definitions"]
    assert found["blocking"]["deck-definitions"][0].startswith("deck/deck.yml is not")
    assert list(found["deferred"]) == ["raw-latex"]


def test_check_content_deferred_setting_replaces_the_default(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "deckz.yml", "checks:\n  deferred: []\n")
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    with raises(SystemExit) as exc_info:
        main(("check", "content", "--plain"))

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.startswith("blocking\traw-latex\t")


def test_check_content_fails_on_a_deferred_check_named(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    with raises(SystemExit) as exc_info:
        main(("check", "content", "raw-latex"))

    assert exc_info.value.code == 1
    assert "#### raw-latex\n" in capsys.readouterr().out


def test_check_content_rejects_an_unknown_check(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    with raises(SystemExit) as exc_info:
        main(("check", "content", "no-such-check"))

    assert exc_info.value.code == 2


def test_check_content_skips_opt_in_checks_unless_named(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "deckz.yml", "checks:\n  opt_in: [raw-latex]\n")
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check", "content"))
    assert capsys.readouterr().out == ""

    with raises(SystemExit) as exc_info:
        main(("check", "content", "raw-latex"))
    assert exc_info.value.code == 1
    assert "notes.tex" in capsys.readouterr().out


def test_check_content_staged_ignores_unstaged_changes(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    import subprocess

    _write(repo / "deckz.yml", "{}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check", "content", "--staged"))

    assert capsys.readouterr().out == ""
