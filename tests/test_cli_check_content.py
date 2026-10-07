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

    with raises(SystemExit) as exc_info:
        main(("check",))

    assert exc_info.value.code == 1
    assert "notes.tex" in capsys.readouterr().out


def test_check_content_plain_reports_a_problem(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    with raises(SystemExit) as exc_info:
        main(("check", "content", "--plain"))

    assert exc_info.value.code == 1
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("raw-latex\t")


def test_check_content_rejects_an_unknown_check(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    with raises(SystemExit) as exc_info:
        main(("check", "content", "no-such-check"))

    assert exc_info.value.code == 2


def test_check_content_staged_ignores_unstaged_changes(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    import subprocess

    _write(repo / "deckz.yml", "{}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check", "content", "--staged"))

    assert capsys.readouterr().out == ""
