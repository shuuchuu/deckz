import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.app import create_app
from studioz.background import changes
from studioz.commits import blocked

ORIGIN = {"Origin": "http://localhost:8421"}
FORM = "/espaces/demo/commit/formulaire"
X = "content/a/x.md"
EN = "content/a/en/x.md"
COMMIT = "/espaces/demo/commit"


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


def _write(workspace: Path, path: str, text: str = "x\n") -> None:
    file = workspace / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf8")


@fixture
def committer(repository: Path, workspace: Path) -> TestClient:
    for path in ("content/a/x.md", "content/a/en/x.md", "client/abc/notes.txt"):
        _write(workspace, path)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", "Content")
    # The commit's author, as the person's own git configuration gives it.
    _git(workspace, "config", "user.name", "Person")
    _git(workspace, "config", "user.email", "person@example.com")
    return TestClient(create_app(repository), base_url="http://localhost:8421")


def _committed(workspace: Path) -> tuple[str, list[str]]:
    message = _git(workspace, "log", "-1", "--format=%B").strip()
    files = _git(workspace, "show", "--name-only", "--format=", "HEAD").split()
    return message, files


def test_dialog_lists_the_changes_all_chosen(
    committer: TestClient, workspace: Path
) -> None:
    _write(workspace, "client/abc/notes.txt", "changed\n")
    _write(workspace, "README.md")

    page = committer.post(
        FORM, data={"formation": "client/abc", "lang": "fr"}, headers=ORIGIN
    ).text

    assert 'name="path" value="client/abc/notes.txt" checked' in page
    assert 'name="path" value="README.md" checked' in page
    assert "Committer 2 fichiers" in page
    assert "Lang-sync" not in page


def test_commit_only_the_files_chosen(committer: TestClient, workspace: Path) -> None:
    _write(workspace, "client/abc/notes.txt", "changed\n")
    _write(workspace, "README.md")
    # Staged in a terminal, but not chosen: it stays out.
    _write(workspace, "other.txt")
    _git(workspace, "add", "other.txt")

    response = committer.post(
        COMMIT,
        data={
            "listed": ["client/abc/notes.txt", "README.md", "other.txt"],
            "path": ["client/abc/notes.txt"],
            "message": "Update the notes\n\nWhy.",
        },
        headers=ORIGIN,
    )

    assert response.status_code == 200
    assert "workspace-changed" in response.headers["HX-Trigger"]
    assert "« Update the notes » enregistré" in response.text
    assert _committed(workspace) == (
        "Update the notes\n\nWhy.",
        ["client/abc/notes.txt"],
    )
    assert _git(workspace, "log", "-1", "--format=%an").strip() == "Person"
    left = {change.path: change.status for change in changes(workspace)}
    assert left == {"README.md": "??", "other.txt": "??"}
    # What's left is listed, still not chosen, with an empty message.
    assert 'name="path" value="README.md">' in response.text
    assert "</textarea>" in response.text
    assert ">Update the notes" not in response.text


def test_a_file_changed_since_the_dialog_opened_is_left_out(
    committer: TestClient, workspace: Path
) -> None:
    _write(workspace, "client/abc/notes.txt", "changed\n")
    _write(workspace, "README.md")

    committer.post(
        COMMIT,
        data={
            "listed": ["client/abc/notes.txt"],
            "path": ["client/abc/notes.txt"],
            "message": "Notes",
        },
        headers=ORIGIN,
    )

    assert _committed(workspace)[1] == ["client/abc/notes.txt"]


def test_nothing_chosen_or_no_message(committer: TestClient, workspace: Path) -> None:
    _write(workspace, "README.md")
    head = _git(workspace, "rev-parse", "HEAD")

    page = committer.post(
        COMMIT, data={"listed": ["README.md"], "message": "Readme"}, headers=ORIGIN
    ).text
    assert "Cochez au moins un fichier" in page
    page = committer.post(
        COMMIT, data={"path": "README.md", "message": "  "}, headers=ORIGIN
    ).text
    assert "Écrivez le message" in page

    assert _git(workspace, "rev-parse", "HEAD") == head


def test_one_language_changed_asks_why(committer: TestClient, workspace: Path) -> None:
    _write(workspace, "content/a/x.md", "changed\n")
    head = _git(workspace, "rev-parse", "HEAD")

    page = committer.post(FORM, data={}, headers=ORIGIN).text
    assert "<code>content/a/x.md</code> (pas <code>content/a/en/x.md</code>)" in page
    assert 'data-agent-task="traduire"' in page
    assert '{"changed": "content/a/x.md", "other": "content/a/en/x.md"}' in page
    assert 'value="only"' in page

    page = committer.post(
        COMMIT, data={"path": X, "message": "Typo"}, headers=ORIGIN
    ).text
    assert "sans leur version dans l'autre langue" in page
    assert _git(workspace, "rev-parse", "HEAD") == head
    page = committer.post(
        COMMIT, data={"path": X, "message": "Typo", "lang_sync": "only"}, headers=ORIGIN
    ).text
    assert "Dites pourquoi" in page
    assert ">Typo</textarea>" in page

    committer.post(
        COMMIT,
        data={
            "path": X,
            "message": "Typo",
            "lang_sync": "only",
            "reason": " une\ncoquille ",
        },
        headers=ORIGIN,
    )
    assert _committed(workspace)[0] == "Typo\n\nLang-sync: fr-only (une coquille)"


def test_lang_sync_pending_or_written_in_the_message(
    committer: TestClient, workspace: Path
) -> None:
    _write(workspace, "content/a/en/x.md", "changed\n")
    committer.post(
        COMMIT,
        data={"path": EN, "message": "New text", "lang_sync": "pending"},
        headers=ORIGIN,
    )
    assert _committed(workspace)[0] == "New text\n\nLang-sync: pending"

    _write(workspace, "content/a/x.md", "changed\n")
    message = "Typo\n\nLang-sync: fr-only (typo)"
    committer.post(COMMIT, data={"path": X, "message": message}, headers=ORIGIN)
    assert _committed(workspace)[0] == message


def test_both_languages_chosen_need_no_reason(
    committer: TestClient, workspace: Path
) -> None:
    _write(workspace, "content/a/x.md", "changed\n")
    _write(workspace, "content/a/en/x.md", "changed\n")

    page = committer.post(FORM, data={}, headers=ORIGIN).text
    assert "Lang-sync" not in page
    # Leaving one out makes it one-sided.
    page = committer.post(
        FORM,
        data={
            "listed": ["content/a/x.md", "content/a/en/x.md"],
            "path": "content/a/x.md",
        },
        headers=ORIGIN,
    ).text
    assert "(pas <code>content/a/en/x.md</code>)" in page

    committer.post(COMMIT, data={"path": [X, EN], "message": "Both"}, headers=ORIGIN)
    assert _committed(workspace) == ("Both", ["content/a/en/x.md", "content/a/x.md"])


def test_a_hook_refusal_is_shown(
    committer: TestClient, workspace: Path, repository: Path
) -> None:
    hook = repository / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        f'#!/bin/sh\necho "{workspace}/client/abc/notes.txt: bad" >&2\nexit 1\n',
        encoding="utf8",
    )
    hook.chmod(0o755)
    _write(workspace, "client/abc/notes.txt", "changed\n")
    head = _git(workspace, "rev-parse", "HEAD")

    page = committer.post(
        COMMIT,
        data={"path": "client/abc/notes.txt", "message": "Notes"},
        headers=ORIGIN,
    ).text

    assert "Le dépôt a refusé ce commit" in page
    assert "client/abc/notes.txt: bad" in page
    assert 'data-agent-task="corriger"' in page
    assert str(workspace) not in page
    assert ">Notes</textarea>" in page
    assert _git(workspace, "rev-parse", "HEAD") == head
    assert (workspace / "client/abc/notes.txt").read_text() == "changed\n"


def test_a_rename_commits_both_paths(committer: TestClient, workspace: Path) -> None:
    _git(workspace, "mv", "client/abc/notes.txt", "client/abc/moved.txt")
    page = committer.post(FORM, data={}, headers=ORIGIN).text
    assert 'value="client/abc/moved.txt" checked' in page

    committer.post(
        COMMIT, data={"path": "client/abc/moved.txt", "message": "Move"}, headers=ORIGIN
    )

    assert not changes(workspace)
    files = _git(workspace, "show", "--name-status", "--format=", "HEAD").split()
    assert files[0].startswith("R")
    assert files[1:] == ["client/abc/notes.txt", "client/abc/moved.txt"]


def test_blocked_during_a_merge(committer: TestClient, workspace: Path) -> None:
    _write(workspace, "README.md")
    assert blocked(workspace, changes(workspace)) is None
    merge_head = (
        workspace / _git(workspace, "rev-parse", "--git-path", "MERGE_HEAD").strip()
    )
    merge_head.write_text(_git(workspace, "rev-parse", "HEAD"), encoding="utf8")

    page = committer.post(
        COMMIT, data={"path": "README.md", "message": "Readme"}, headers=ORIGIN
    ).text

    assert "fusion est en cours" in page
    assert "README.md" in {change.path for change in changes(workspace)}


def test_commit_refused_from_another_site(
    committer: TestClient, workspace: Path
) -> None:
    _write(workspace, "README.md")
    response = committer.post(
        COMMIT,
        data={"path": "README.md", "message": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert changes(workspace)
