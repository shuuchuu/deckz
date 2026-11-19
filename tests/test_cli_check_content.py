import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, LogCaptureFixture, fixture, raises

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


def test_check_staged_only_counts_the_deferred_problems(
    repo: Path, capsys: CaptureFixture[str], caplog: LogCaptureFixture
) -> None:
    import subprocess

    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    with caplog.at_level("INFO"):
        main(("check", "--staged"))  # Should not raise: raw-latex is deferred.

    assert capsys.readouterr().out == ""
    assert "1 problem of deferred checks in the staged files (raw-latex 1)" in (
        caplog.text
    )


def _commit_all(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        cwd=repo,
        check=True,
    )


def test_check_staged_counts_the_deferred_problems_of_the_staged_files_only(
    repo: Path, capsys: CaptureFixture[str], caplog: LogCaptureFixture
) -> None:
    import subprocess

    _write(repo / "content" / "topic" / "old.tex", r"\section{x}")
    _commit_all(repo)
    _write(repo / "content" / "topic" / "new.tex", r"\section{x}")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    with caplog.at_level("INFO"):
        main(("check", "--staged"))

    assert "1 problem of deferred checks in the staged files (raw-latex 1)" in (
        caplog.text
    )
    main(("check", "--plain"))  # Without --staged: the whole backlog.
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_check_staged_leaves_out_the_checks_needing_other_files(
    repo: Path, capsys: CaptureFixture[str], caplog: LogCaptureFixture
) -> None:
    import subprocess

    _write(repo / "deckz.yml", "checks:\n  not_after_edit: [raw-latex]\n")
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    with caplog.at_level("INFO"):
        main(("check", "--staged"))

    assert "raw-latex not run on a commit (checks.not_after_edit" in caplog.text
    assert "problem of deferred checks" not in caplog.text


def test_check_staged_runs_blocking_checks_on_the_whole_export(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    import subprocess

    _write(repo / "deckz.yml", "checks:\n  deferred: []\n")
    _write(repo / "content" / "topic" / "old.tex", r"\section{x}")
    _commit_all(repo)
    _write(repo / "content" / "topic" / "notes.md", "# Notes\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    with raises(SystemExit) as exc_info:
        main(("check", "--staged", "--plain"))

    assert exc_info.value.code == 1
    assert "old.tex" in capsys.readouterr().out


def test_check_timings_report_each_check(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    main(("check", "content", "--json", "--timings"))

    found = json.loads(capsys.readouterr().out)
    assert set(found["timings"]["raw-latex"]) == {"cpu", "wall"}
    assert "deck-definitions" in found["timings"]


def test_a_check_in_a_thread_reports_as_the_others(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _write(repo / "deckz.yml", "checks:\n  in_thread: [raw-latex, jinja-syntax]\n")
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")

    main(("check", "content", "--plain"))

    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("deferred\traw-latex\tcontent/topic/notes.tex: ")


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


def _stage_raw_latex(repo: Path, triggers: str) -> None:
    import subprocess

    _write(
        repo / "deckz.yml",
        f"checks:\n  deferred: []\n  staged_triggers:\n    raw-latex: {triggers}\n",
    )
    _write(repo / "content" / "topic" / "notes.tex", r"\section{x}")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)


def test_check_staged_skips_a_check_no_staged_change_triggers(
    repo: Path, capsys: CaptureFixture[str], caplog: LogCaptureFixture
) -> None:
    _stage_raw_latex(repo, '["*.py"]')

    with caplog.at_level("INFO"):
        main(("check", "--staged"))

    assert capsys.readouterr().out == ""
    assert "raw-latex not run: no staged change matches" in caplog.text


def test_check_staged_runs_a_check_a_staged_change_triggers(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _stage_raw_latex(repo, '["content/*.tex"]')

    with raises(SystemExit) as exc_info:
        main(("check", "--staged", "--plain"))

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.startswith("blocking\traw-latex\t")


def test_check_staged_runs_a_triggered_check_named(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _stage_raw_latex(repo, '["*.py"]')

    with raises(SystemExit) as exc_info:
        main(("check", "--staged", "raw-latex"))

    assert exc_info.value.code == 1


def test_check_without_staged_runs_a_triggered_check(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    _stage_raw_latex(repo, '["*.py"]')

    with raises(SystemExit) as exc_info:
        main(("check", "--plain"))

    assert exc_info.value.code == 1


def test_staged_changes_list_a_deleted_file(repo: Path) -> None:
    import subprocess

    from deckz.checking import staged_changes

    _write(repo / "tools" / "a.py", "x = 1\n")
    _write(repo / "README.md", "x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "rm", "-q", "tools/a.py"], cwd=repo, check=True)

    assert staged_changes(repo) == ["tools/a.py"]
