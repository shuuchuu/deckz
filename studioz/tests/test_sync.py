import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.sync import Upstream, abort, check, continue_rebase, publish, state
from studioz.sync import update as sync_update
from studioz.sync import upstream as find_upstream

ORIGIN = {"Origin": "http://localhost:8421"}
SYNC = "/espaces/demo/synchronisation"

# Stands for the workspace's own deckz: `check --staged` fails when the index
# it checks holds a `bad.md`; `hooks check-commits` passes.
_FAKE_DECKZ = """#!/bin/sh
if [ "$1" = check ]; then
    if git ls-files | grep -q bad.md; then echo "bad.md: bad content"; exit 1; fi
    echo "checked $(git ls-files | wc -l) files"
fi
"""


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
    ).stdout.strip()


def _write(root: Path, path: str, text: str = "x\n") -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@fixture
def remote(repository: Path, tmp_path: Path) -> Path:
    """A bare `origin` the main checkout's `main` tracks.

    Returns:
        A clone of it, where others push.
    """
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "--quiet", "--bare", str(repository), str(bare))
    _git(repository, "remote", "add", "origin", str(bare))
    _git(repository, "fetch", "--quiet", "origin")
    _git(repository, "branch", "--set-upstream-to=origin/main")
    (repository / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf8")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "--quiet", str(bare), str(other))
    return other


@fixture
def synced(remote: Path, workspace: Path) -> Path:
    deckz = workspace / ".venv" / "bin" / "deckz"
    deckz.parent.mkdir(parents=True)
    deckz.write_text(_FAKE_DECKZ, encoding="utf8")
    deckz.chmod(0o755)
    return workspace


def _up(repository: Path) -> Upstream:
    found = find_upstream(repository)
    assert found is not None
    return found


def test_upstream(repository: Path, remote: Path) -> None:
    assert find_upstream(repository) == Upstream(
        "origin", "main", "refs/remotes/origin/main"
    )


def test_no_upstream(repository: Path, workspace: Path, client: TestClient) -> None:
    assert find_upstream(repository) is None
    assert "pas de branche amont" in client.get(SYNC).text


def test_update_rebases_onto_the_upstream_branch(
    repository: Path, remote: Path, synced: Path
) -> None:
    up = _up(repository)
    _write(synced, "mine.md")
    _commit(synced, "Mine")
    _write(synced, "uncommitted.md", "work\n")
    _git(synced, "add", "uncommitted.md")
    _write(remote, "theirs.md")
    theirs = _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")

    outcome = sync_update(synced, up)

    assert outcome.ok, outcome.output
    assert "1 commit de origin/main" in outcome.message
    assert _git(synced, "rev-parse", "HEAD~1") == theirs
    found = state(synced, up)
    assert [commit.subject for commit in found.ahead] == ["Mine"]
    assert found.behind == 0
    assert found.fetched is not None
    # The uncommitted work came along.
    assert (synced / "uncommitted.md").read_text() == "work\n"
    # The main checkout's files didn't move.
    assert not (repository / "theirs.md").exists()


def test_conflict_fixed_then_continued(
    repository: Path, remote: Path, synced: Path
) -> None:
    up = _up(repository)
    _write(synced, "shared.md", "mine\n")
    _commit(synced, "Mine")
    _write(remote, "shared.md", "theirs\n")
    _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")

    outcome = sync_update(synced, up)

    assert not outcome.ok
    assert "Conflit" in outcome.message
    assert state(synced, up).conflicts == ("shared.md",)
    refused = continue_rebase(synced)
    assert not refused.ok
    assert "shared.md" in refused.message

    _write(synced, "shared.md", "both\n")
    assert continue_rebase(synced).ok
    found = state(synced, up)
    assert found.conflicts is None
    assert [commit.subject for commit in found.ahead] == ["Mine"]
    assert _git(synced, "show", "HEAD:shared.md") == "both"


def test_conflict_aborted(repository: Path, remote: Path, synced: Path) -> None:
    up = _up(repository)
    _write(synced, "shared.md", "mine\n")
    mine = _commit(synced, "Mine")
    _write(remote, "shared.md", "theirs\n")
    _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")
    sync_update(synced, up)

    assert abort(synced).ok

    assert _git(synced, "rev-parse", "HEAD") == mine
    assert state(synced, up).conflicts is None
    assert (synced / "shared.md").read_text() == "mine\n"


def test_check_checks_the_commit_not_the_files(
    repository: Path, remote: Path, synced: Path
) -> None:
    up = _up(repository)
    _write(synced, "good.md")
    good = _commit(synced, "Good")
    _write(synced, "bad.md")  # Not committed: not pushed, not checked.

    passed = check(synced, up, good)
    assert passed.ok, passed.output
    assert passed.checked == good

    bad = _commit(synced, "Bad")
    failed = check(synced, up, bad)
    assert not failed.ok
    assert "bad.md: bad content" in failed.output
    assert failed.checked is None
    # The workspace's own index is untouched.
    assert not _git(synced, "diff", "--cached", "--name-only")


def test_publish_pushes_the_commit_checked(
    repository: Path, remote: Path, synced: Path
) -> None:
    up = _up(repository)
    _write(synced, "mine.md")
    first = _commit(synced, "Mine")
    _write(synced, "more.md")
    _commit(synced, "More")

    moved = publish(synced, up, first)
    assert not moved.ok
    assert "a changé depuis la vérification" in moved.message

    head = _git(synced, "rev-parse", "HEAD")
    assert publish(synced, up, head).ok
    assert _git(remote, "ls-remote", "origin", "main").split()[0] == head
    assert not state(synced, up).ahead
    # The main checkout's branch and files didn't move.
    assert _git(repository, "rev-parse", "main") != head
    assert not (repository / "mine.md").exists()


def test_publish_never_forces(repository: Path, remote: Path, synced: Path) -> None:
    up = _up(repository)
    _write(synced, "mine.md")
    mine = _commit(synced, "Mine")
    _write(remote, "theirs.md")
    _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")

    outcome = publish(synced, up, mine)

    assert not outcome.ok
    assert "mettez à jour" in outcome.message
    assert _git(remote, "ls-remote", "origin", "main").split()[0] != mine


def test_sync_dialog_from_check_to_publish(
    repository: Path, remote: Path, synced: Path, client: TestClient
) -> None:
    _write(synced, "mine.md")
    _commit(synced, "Mine")
    _write(remote, "theirs.md")
    _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")

    panel = client.get(SYNC).text
    assert "1 commit à publier" in panel
    page = client.post(f"{SYNC}/formulaire", headers=ORIGIN).text
    assert "Mine" in page
    assert "Mettre à jour et vérifier" in page

    response = client.post(f"{SYNC}/verifier", headers=ORIGIN)
    assert "workspace-changed" in response.headers["HX-Trigger"]
    head = _git(synced, "rev-parse", "HEAD")
    assert "Les vérifications passent" in response.text
    assert f'{{"sha": "{head}"}}' in response.text
    assert "Publier 1 commit sur origin/main" in response.text

    page = client.post(f"{SYNC}/publier", data={"sha": head}, headers=ORIGIN).text
    assert "Publié sur origin/main" in page
    assert _git(remote, "ls-remote", "origin", "main").split()[0] == head


def test_sync_dialog_conflict(
    repository: Path, remote: Path, synced: Path, client: TestClient
) -> None:
    _write(synced, "shared.md", "mine\n")
    _commit(synced, "Mine")
    _write(remote, "shared.md", "theirs\n")
    _commit(remote, "Theirs")
    _git(remote, "push", "--quiet", "origin", "main")

    page = client.post(f"{SYNC}/verifier", headers=ORIGIN).text
    assert "<code>shared.md</code>" in page
    # Over a deck's page, the file opens in its editor.
    page = client.post(
        f"{SYNC}/formulaire", data={"formation": "client/abc"}, headers=ORIGIN
    ).text
    assert 'class="change" data-file="shared.md"' in page
    assert 'data-agent-task="conflit"' in page
    assert '"path": ["shared.md"]' in page
    assert "Continuer" in page
    assert "Publier" not in page
    assert "conflit" in client.get(SYNC).text

    page = client.post(f"{SYNC}/abandonner", headers=ORIGIN).text
    assert "Mise à jour abandonnée" in page


def test_sync_refused_from_another_site(
    remote: Path, synced: Path, client: TestClient
) -> None:
    _write(synced, "mine.md")
    head = _commit(synced, "Mine")
    response = client.post(
        f"{SYNC}/publier",
        data={"sha": head},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert _git(remote, "ls-remote", "origin", "main").split()[0] != head
