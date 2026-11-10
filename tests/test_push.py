"""`deckz push`, on git repositories and bare remotes made in a temporary directory.

copierz runs for real (the `push` extra is in the dev group), on a lab clone
of the test's own.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from pytest import fixture, raises

from deckz.cli import main
from deckz.status import LABS_PUBLISH_FIX, StatusItem


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone_of_new_remote(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    # A bare remote `<name>.git` with one commit of `files`, and a clone `name`.
    remote = tmp_path / "remotes" / f"{name}.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    clone = tmp_path / name
    _git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    for path, content in files.items():
        (clone / path).write_text(content, encoding="utf8")
    _git(clone, "add", *files)
    _git(clone, "commit", "--quiet", "-m", "Initial")
    _git(clone, "push", "--quiet", "origin", "HEAD:main")
    _git(clone, "branch", "--quiet", "--set-upstream-to=origin/main")
    return clone


def _commit(clone: Path, message: str) -> None:
    _git(clone, "commit", "--quiet", "--allow-empty", "-m", message)


def _remote_tip(clone: Path, branch: str = "main") -> str:
    return _git(clone, "ls-remote", "origin", f"refs/heads/{branch}").split()[0]


@fixture
def repos(tmp_path: Path, monkeypatch: Any) -> dict[str, Path]:
    # A repository, its deckz checkout and a lab's repository, all pushed.
    lab_remote = tmp_path / "remotes" / "lab.git"
    deckz_yml = (
        "labs:\n"
        "  repos:\n"
        "    - repo: owner/lab\n"
        "      lab: some/lab\n"
        f"      url: {lab_remote}\n"
        "      branches: {main: null, solution: main}\n"
        "      start: {fr: main}\n"
    )
    repo = _clone_of_new_remote(tmp_path, "repo", {"deckz.yml": deckz_yml})
    deckz = _clone_of_new_remote(tmp_path, "deckz", {"README.md": "deckz\n"})
    lab = _clone_of_new_remote(
        tmp_path, "lab", {".copier-answers.yml": "_src_path: ../template\n"}
    )
    _git(lab, "switch", "--quiet", "-c", "solution")
    _commit(lab, "Solve")
    _git(lab, "push", "--quiet", "-u", "origin", "solution")
    _git(lab, "switch", "--quiet", "main")
    monkeypatch.setattr("deckz.setting_up.own_checkout", lambda: deckz)
    monkeypatch.chdir(repo)
    return {"repo": repo, "deckz": deckz, "lab": lab}


def _push(capsys: Any, *args: str) -> tuple[int, dict[str, Any]]:
    code = 0
    try:
        main(("push", "--json", *args))
    except SystemExit as exit_:
        code = int(exit_.code or 0)
    return code, json.loads(capsys.readouterr().out)


def _branches(report: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    (repo,) = [r for r in report["repositories"] if r["name"] == name]
    return {b["branch"]: b for b in repo["branches"]}


def test_pushes_deckz_then_the_labs_then_the_repository(
    repos: dict[str, Path], capsys: Any
) -> None:
    _commit(repos["deckz"], "Fix deckz")
    _commit(repos["deckz"], "Fix deckz again")
    _commit(repos["lab"], "Fix the lab")
    _commit(repos["repo"], "Use the fix")

    code, report = _push(capsys)

    assert code == 0
    assert report["ok"]
    assert [r["name"] for r in report["repositories"]] == ["deckz", "owner/lab", "repo"]
    assert _branches(report, "deckz")["main"]["outcome"] == "pushed"
    assert _branches(report, "deckz")["main"]["commits"] == 2
    assert _branches(report, "owner/lab")["main"]["outcome"] == "pushed"
    assert _branches(report, "owner/lab")["solution"]["outcome"] == "up to date"
    assert _branches(report, "repo")["main"]["commits"] == 1
    for clone in repos.values():
        assert _remote_tip(clone) == _git(clone, "rev-parse", "HEAD")


def test_a_dry_run_pushes_nothing(repos: dict[str, Path], capsys: Any) -> None:
    before = {name: _remote_tip(clone) for name, clone in repos.items()}
    for clone in repos.values():
        _commit(clone, "Change")

    code, report = _push(capsys, "--dry-run")

    assert code == 0
    assert report["dry_run"]
    assert _branches(report, "deckz")["main"]["outcome"] == "would push"
    assert _branches(report, "owner/lab")["main"]["outcome"] == "would push"
    assert _branches(report, "repo")["main"]["outcome"] == "would push"
    assert {name: _remote_tip(clone) for name, clone in repos.items()} == before


def test_a_diverged_deckz_stops_before_the_rest(
    repos: dict[str, Path], tmp_path: Path, capsys: Any
) -> None:
    other = tmp_path / "other-deckz"
    _git(
        tmp_path,
        "clone",
        "--quiet",
        str(tmp_path / "remotes" / "deckz.git"),
        str(other),
    )
    _commit(other, "Someone else's fix")
    _git(other, "push", "--quiet", "origin", "main")
    _commit(repos["deckz"], "My fix")
    _commit(repos["repo"], "Use my fix")
    before = _remote_tip(repos["repo"])

    code, report = _push(capsys)

    assert code == 1
    deckz = _branches(report, "deckz")["main"]
    assert deckz["state"] == "diverged"
    assert "pull --rebase" in deckz["detail"]
    assert "nothing else was" in report["stopped"]
    assert [r["name"] for r in report["repositories"]] == ["deckz"]
    assert _remote_tip(repos["repo"]) == before


def test_a_repository_behind_its_remote_is_left_without_failing(
    repos: dict[str, Path], tmp_path: Path, capsys: Any
) -> None:
    other = tmp_path / "other-repo"
    _git(
        tmp_path, "clone", "--quiet", str(tmp_path / "remotes" / "repo.git"), str(other)
    )
    _commit(other, "Someone else's change")
    _git(other, "push", "--quiet", "origin", "main")

    code, report = _push(capsys)

    assert code == 0
    branch = _branches(report, "repo")["main"]
    assert branch["state"] == "behind"
    assert branch["outcome"] == "not pushed"
    assert "pull" in branch["detail"]


def test_a_rebased_lab_branch_needs_force(repos: dict[str, Path], capsys: Any) -> None:
    lab = repos["lab"]
    _commit(lab, "Fix the statement")
    _git(lab, "push", "--quiet", "origin", "main")
    _git(lab, "switch", "--quiet", "solution")
    _git(lab, "rebase", "--quiet", "main")
    _git(lab, "switch", "--quiet", "main")

    _commit(repos["repo"], "Link the fixed statement")
    before = _remote_tip(repos["repo"])

    code, report = _push(capsys)

    assert code == 1
    solution = _branches(report, "owner/lab")["solution"]
    assert solution["state"] == "rewritten"
    assert "`deckz push --force`" in solution["detail"]
    # Its content links to the lab's branches: the repository waits for them.
    assert "owner/lab wasn't pushed, so the repository was not" in report["stopped"]
    assert [r["name"] for r in report["repositories"]] == ["deckz", "owner/lab"]
    assert _remote_tip(repos["repo"]) == before

    code, report = _push(capsys, "--force")

    assert code == 0
    assert _branches(report, "owner/lab")["solution"]["outcome"] == "pushed"
    assert _remote_tip(lab, "solution") == _git(lab, "rev-parse", "solution")
    assert _branches(report, "repo")["main"]["outcome"] == "pushed"


def test_a_failing_lab_stops_the_repository_not_the_other_labs(
    repos: dict[str, Path], tmp_path: Path, capsys: Any
) -> None:
    other_lab = _clone_of_new_remote(
        tmp_path, "other-lab", {".copier-answers.yml": "_src_path: ../template\n"}
    )
    deckz_yml = repos["repo"] / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8")
        + "    - repo: owner/other-lab\n"
        + "      lab: other/lab\n"
        + f"      url: {tmp_path / 'remotes' / 'other-lab.git'}\n"
        + "      branches: {main: null}\n"
        + "      start: {fr: main}\n",
        encoding="utf8",
    )
    someone = tmp_path / "someone-lab"
    _git(
        tmp_path,
        "clone",
        "--quiet",
        str(tmp_path / "remotes" / "lab.git"),
        str(someone),
    )
    _commit(someone, "Theirs")
    _git(someone, "push", "--quiet", "origin", "main")
    _commit(repos["lab"], "Mine")
    _commit(other_lab, "Fix the other lab")
    _commit(repos["repo"], "Link both")
    before = _remote_tip(repos["repo"])

    code, report = _push(capsys, "--dry-run")

    assert code == 1
    assert (
        "owner/lab wouldn't be pushed, so the repository would not be"
        in (report["stopped"])
    )
    assert _branches(report, "owner/other-lab")["main"]["outcome"] == "would push"

    code, report = _push(capsys)

    assert code == 1
    assert _branches(report, "owner/lab")["main"]["state"] == "diverged"
    assert _branches(report, "owner/other-lab")["main"]["outcome"] == "pushed"
    assert "repo" not in [r["name"] for r in report["repositories"]]
    assert report["publish"] == []
    assert _remote_tip(repos["repo"]) == before


def test_a_lab_with_no_local_clone_is_skipped(
    repos: dict[str, Path], capsys: Any
) -> None:
    repos["lab"].rename(repos["lab"].with_name("elsewhere"))
    _commit(repos["repo"], "Change")

    code, report = _push(capsys)

    assert code == 0
    (lab,) = [r for r in report["repositories"] if r["name"] == "owner/lab"]
    assert "no local clone" in lab["skipped"]
    assert _branches(report, "repo")["main"]["outcome"] == "pushed"


def test_without_copierz_the_labs_are_skipped_and_the_rest_pushed(
    repos: dict[str, Path], capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr("deckz.pushing.copierz_command", lambda: None)
    _commit(repos["lab"], "Fix the lab")
    _commit(repos["repo"], "Change")
    before = _remote_tip(repos["lab"])

    code, report = _push(capsys)

    assert code == 0
    (lab,) = [r for r in report["repositories"] if r["name"] == "owner/lab"]
    assert "deckz[push]" in lab["skipped"]
    assert not lab["problem"]
    assert _remote_tip(repos["lab"]) == before
    assert _branches(report, "repo")["main"]["outcome"] == "pushed"


@fixture
def labs_left(monkeypatch: Any) -> list[str]:
    # One notebook left to publish, and a publish that only records its calls.
    calls: list[str] = []
    item = StatusItem("1 notebook of origin/main not as published: x", LABS_PUBLISH_FIX)
    monkeypatch.setattr("deckz.status.unpublished", lambda *_, **__: ([item], []))

    def publish_labs(*_: Any, **__: Any) -> tuple[bool, None]:
        calls.append("labs")
        return True, None

    monkeypatch.setattr("deckz.publishing.publish_labs", publish_labs)
    return calls


def test_without_publish_says_what_is_left(
    repos: dict[str, Path], capsys: Any, labs_left: list[str]
) -> None:
    code, report = _push(capsys)

    assert code == 0
    (labs,) = report["publish"]
    assert labs["outcome"] == "left"
    assert "deckz push --publish" in labs["detail"]
    assert labs_left == []


def test_publish_publishes_what_is_left(
    repos: dict[str, Path], capsys: Any, labs_left: list[str]
) -> None:
    code, report = _push(capsys, "--dry-run", "--publish")

    assert code == 0
    assert report["publish"][0]["outcome"] == "would publish"
    assert labs_left == []

    code, report = _push(capsys, "--publish")

    assert code == 0
    assert report["publish"][0]["outcome"] == "published"
    assert labs_left == ["labs"]


def test_the_text_report(repos: dict[str, Path], capsys: Any) -> None:
    _commit(repos["repo"], "Change")

    main(("push", "--dry-run"))

    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "would push main: 1 commit(s) to push to origin/main" in out
    assert "Nothing left to publish." in out


def test_dry_run_on_a_diverged_repository_exits_1(
    repos: dict[str, Path], tmp_path: Path
) -> None:
    other = tmp_path / "other-repo"
    _git(
        tmp_path, "clone", "--quiet", str(tmp_path / "remotes" / "repo.git"), str(other)
    )
    _commit(other, "Theirs")
    _git(other, "push", "--quiet", "origin", "main")
    _commit(repos["repo"], "Mine")

    with raises(SystemExit) as exc_info:
        main(("push", "--dry-run"))

    assert exc_info.value.code == 1
