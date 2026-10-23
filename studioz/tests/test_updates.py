import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.sync import upstream as find_upstream
from studioz.updates import Fetcher, SetupProblem

from studioz import app as studio_app
from studioz import updates

ORIGIN = {"Origin": "http://localhost:8421"}
BANNER = "/espaces/demo/mise-a-jour"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _studio(client: TestClient) -> Any:
    return client.app.state.studio  # ty: ignore[unresolved-attribute]


def _push_theirs(remote: Path, name: str = "theirs.md") -> None:
    (remote / name).write_text("theirs\n", encoding="utf8")
    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", f"Add {name}")
    _git(remote, "push", "--quiet", "origin", "main")


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
    other = tmp_path / "other"
    _git(tmp_path, "clone", "--quiet", str(bare), str(other))
    return other


@fixture
def setups(monkeypatch: Any) -> list[tuple[Path, bool]]:
    """Stands for the workspaces' `deckz setup`: each call, and a problem.

    Returns:
        The calls, as `(workspace, force)`.
    """
    calls: list[tuple[Path, bool]] = []

    def setup(workspace: Path, *, force: bool) -> tuple[SetupProblem, ...]:
        calls.append((workspace, force))
        return (SetupProblem("deckz", "../deckz is 2 commits behind origin/main"),)

    monkeypatch.setattr("studioz.updates._setup_problems", setup)
    return calls


def test_fetcher_says_whether_the_branch_moved(repository: Path, remote: Path) -> None:
    up = find_upstream(repository)
    assert up is not None
    # The fixture's own fetch wrote one; studioz's write none.
    (repository / ".git" / "FETCH_HEAD").unlink()
    fetcher = Fetcher()

    assert fetcher.fetch(repository, up) is False
    assert fetcher.fetched is not None
    _push_theirs(remote)
    assert fetcher.fetch(repository, up) is True
    assert not (repository / ".git" / "FETCH_HEAD").exists()

    _git(repository, "remote", "set-url", "origin", str(remote.parent / "gone.git"))
    assert fetcher.fetch(repository, up) is False
    assert fetcher.error


def test_a_clean_workspace_behind_is_fast_forwarded_and_set_up(
    repository: Path,
    remote: Path,
    workspace: Path,
    setups: list[tuple[Path, bool]],
    client: TestClient,
) -> None:
    _push_theirs(remote)
    studio = _studio(client)

    studio_app._keep_current(studio)

    assert _git(workspace, "rev-parse", "HEAD") == _git(remote, "rev-parse", "HEAD")
    assert setups == [(workspace, False)]
    update = updates.applied(workspace)
    assert update is not None
    assert (update.commits, update.automatic, update.setup_running) == (1, True, False)
    banner = client.get(BANNER).text
    assert "Mis à jour automatiquement" in banner
    assert "1 commit de origin/main" in banner
    assert "../deckz is 2 commits behind origin/main" in banner
    assert "deckz setup : 1 problème" in banner

    client.post(f"{BANNER}/vu", headers=ORIGIN)
    assert "Mis à jour" not in client.get(BANNER).text


def test_package_json_changing_forces_the_setup_steps(
    repository: Path,
    remote: Path,
    workspace: Path,
    setups: list[tuple[Path, bool]],
    client: TestClient,
) -> None:
    _push_theirs(remote, "package.json")

    studio_app._keep_current(_studio(client))

    assert setups == [(workspace, True)]


def test_a_workspace_with_its_own_work_is_offered_its_update(
    repository: Path,
    remote: Path,
    workspace: Path,
    setups: list[tuple[Path, bool]],
    client: TestClient,
) -> None:
    (workspace / "mine.md").write_text("mine\n", encoding="utf8")
    _push_theirs(remote)
    head = _git(workspace, "rev-parse", "HEAD")

    studio_app._keep_current(_studio(client))

    assert _git(workspace, "rev-parse", "HEAD") == head
    assert setups == []
    banner = client.get(BANNER).text
    assert "origin/main a 1 commit que l&#39;espace n&#39;a pas" not in banner
    assert "origin/main a 1 commit que l'espace n'a pas" in banner
    assert "Mettre à jour…" in banner
    notice = client.get(f"{BANNER}?avis=true").text
    assert "Mettre à jour d'abord" in notice


def test_a_busy_workspace_waits(
    repository: Path,
    remote: Path,
    workspace: Path,
    setups: list[tuple[Path, bool]],
    client: TestClient,
    monkeypatch: Any,
) -> None:
    studio = _studio(client)
    monkeypatch.setattr(studio.agents, "busy", lambda _: True)
    _push_theirs(remote)
    head = _git(workspace, "rev-parse", "HEAD")

    studio_app._keep_current(studio)

    assert _git(workspace, "rev-parse", "HEAD") == head


def test_the_person_s_update_runs_the_setup_too(
    repository: Path,
    remote: Path,
    workspace: Path,
    setups: list[tuple[Path, bool]],
    client: TestClient,
) -> None:
    (workspace / "mine.md").write_text("mine\n", encoding="utf8")
    _git(workspace, "add", "mine.md")
    _git(workspace, "commit", "-qm", "Mine")
    _push_theirs(remote)

    client.post("/espaces/demo/synchronisation/mettre-a-jour", headers=ORIGIN)

    for _ in range(100):
        update = updates.applied(workspace)
        if update is not None and not update.setup_running:
            break
        time.sleep(0.05)
    assert update is not None
    assert (update.commits, update.automatic) == (1, False)
    assert setups == [(workspace, False)]
