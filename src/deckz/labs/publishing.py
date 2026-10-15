"""Replace the labs remote's branch with one commit of the published notebooks.

Each publish force-pushes a single parentless commit, whose tree holds every
notebook committed under the configured notebooks directory, as
`<id>.ipynb`, plus the files committed under the published files directory
(`paths.labs_published_dir`, e.g. a README and a `.devcontainer/` for
Codespaces) at the same paths, and nothing else: trainees see the current
notebooks only, never their history (kept in this repo) nor where a notebook
sits in it. A published notebook name may already be in PDFs handed to
trainees, so a publish refuses to drop any the remote branch already has,
unless told to; the other files come and go freely.

Shells out to `git` (fetch and push need the user's own credentials/ssh
agent, which `git` already picks up from the environment) rather than using
pygit2, which deckz otherwise relies on for read-only repository discovery.
"""

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ..exceptions import LabPublishRefusedError


def _git(
    git_dir: Path,
    *args: str,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    return subprocess.run(
        ["git", "-C", str(git_dir), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
        env=env,
    ).stdout.strip()


def _metadata_id(metadata: dict[str, object], key: str) -> str:
    value: object = metadata
    for part in key.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, str) else ""


def notebook_id(path: Path, id_metadata_key: str) -> str:
    """The published ID a notebook file holds.

    Returns:
        The ID, or "" if it has none.
    """
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return _metadata_id(notebook.get("metadata", {}), id_metadata_key)


def repository_name(git_dir: Path, remote: str) -> str:
    """The name of the repository `remote` points to, e.g. `labs`.

    Codespaces opens a repository in `/workspaces/<its name>`.

    Returns:
        The last part of the remote's URL, or `remote` itself if it has none.
    """
    url = subprocess.run(
        ["git", "-C", str(git_dir), "remote", "get-url", remote],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    match = re.search(r"([^/:]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else remote


def _published_notebooks(
    git_dir: Path,
    notebooks_dir: Path,
    *,
    id_metadata_key: str,
    id_pattern: str,
    not_secrets: Iterable[str] = (),
) -> dict[str, str]:
    """The notebooks committed at HEAD, by ID.

    Returns:
        The blob sha of each ID's notebook.

    Raises:
        LabPublishRefusedError: If a committed notebook has no valid ID, two \
            notebooks share one, or one holds what looks like a credential.
    """
    from .secrets import find_secrets

    valid_id = re.compile(id_pattern)
    notebooks_rel = notebooks_dir.relative_to(git_dir).as_posix()
    published: dict[str, str] = {}
    paths: dict[str, str] = {}
    problems = []
    listing = _git(git_dir, "ls-tree", "-r", "HEAD", "--", notebooks_rel)
    for line in listing.splitlines():
        info, path = line.split("\t", 1)
        sha = info.split()[2]
        if not path.endswith(".ipynb"):
            problems.append(f"not a notebook: {path}")
            continue
        notebook = json.loads(_git(git_dir, "cat-file", "blob", sha))
        problems += [
            f"looks like a credential, in {path}: {finding}"
            for finding in find_secrets(notebook, not_secrets)
        ]
        lab_id = _metadata_id(notebook["metadata"], id_metadata_key)
        if not valid_id.fullmatch(lab_id):
            problems.append(f"no valid ID (run `deckz labs ids`): {path}")
        elif lab_id in published:
            problems.append(f"ID {lab_id} also in {paths[lab_id]}: {path}")
        else:
            published[lab_id] = sha
            paths[lab_id] = path
    if problems:
        msg = "; ".join(problems)
        raise LabPublishRefusedError(msg)
    return published


def _published_files(git_dir: Path, published_dir: Path | None) -> dict[str, str]:
    """The files committed at HEAD under `published_dir`, by published path.

    Returns:
        The `<mode> blob <sha>` of each file, by its path relative to \
        `published_dir` (none if it's None or holds no committed file).

    Raises:
        LabPublishRefusedError: If one would sit among the notebooks: an \
            `.ipynb` file at its root.
    """
    if published_dir is None:
        return {}
    published_rel = published_dir.relative_to(git_dir).as_posix()
    listing = _git(git_dir, "ls-tree", "-r", "HEAD", "--", published_rel)
    files = {}
    for line in listing.splitlines():
        info, path = line.split("\t", 1)
        files[path.removeprefix(published_rel + "/")] = info
    if among := sorted(p for p in files if "/" not in p and p.endswith(".ipynb")):
        msg = (
            f"{published_rel} holds notebooks at its root, where published "
            "notebooks go: " + ", ".join(among)
        )
        raise LabPublishRefusedError(msg)
    return files


def _tree(git_dir: Path, entries: dict[str, str]) -> str:
    # `git mktree` takes one level only: a throwaway index nests the paths.
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(
            git_dir,
            "update-index",
            "--add",
            "--index-info",
            stdin="".join(
                f"{info.split()[0]} {info.split()[2]}\t{path}\n"
                for path, info in sorted(entries.items())
            ),
            env=env,
        )
        return _git(git_dir, "write-tree", env=env)


def publish(
    git_dir: Path,
    notebooks_dir: Path,
    *,
    published_dir: Path | None = None,
    id_metadata_key: str,
    id_pattern: str,
    remote: str,
    branch: str,
    break_published_links: bool = False,
    not_secrets: Iterable[str] = (),
) -> bool:
    """Replace `remote`'s `branch` with one commit of HEAD's lab notebooks.

    The commit also holds the files committed under `published_dir`, at the
    same paths.

    Returns:
        True if a new commit was pushed, False if the remote was already up \
        to date.

    Raises:
        LabPublishRefusedError: If the notebooks directory or \
            `published_dir` has uncommitted changes, a committed notebook \
            has no valid or unique ID or holds what looks like a credential \
            (see `labs.secrets`), `published_dir` holds a notebook at its \
            root, or the publish would drop an already-published notebook \
            (unless `break_published_links`).
    """
    for directory in (notebooks_dir, published_dir):
        if directory is None:
            continue
        rel = directory.relative_to(git_dir).as_posix()
        if _git(git_dir, "status", "--porcelain", "--", rel):
            msg = f"{rel} has uncommitted changes"
            raise LabPublishRefusedError(msg)
    # A non-raising fetch: the branch may not exist yet (first publish), which
    # fails the fetch but is not an error -- the rev-parse below treats a
    # never-published branch the same way either way.
    subprocess.run(
        ["git", "-C", str(git_dir), "fetch", "--quiet", remote, branch],
        capture_output=True,
        text=True,
        check=False,
    )
    published = _published_notebooks(
        git_dir,
        notebooks_dir,
        id_metadata_key=id_metadata_key,
        id_pattern=id_pattern,
        not_secrets=not_secrets,
    )
    tree = _tree(
        git_dir,
        {
            **_published_files(git_dir, published_dir),
            **{
                f"{lab_id}.ipynb": f"100644 blob {sha}"
                for lab_id, sha in published.items()
            },
        },
    )
    remote_ref = f"{remote}/{branch}"
    remote_sha = subprocess.run(
        ["git", "-C", str(git_dir), "rev-parse", "--verify", "--quiet", remote_ref],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    previous: set[str] = set()
    if remote_sha:
        if (
            _git(git_dir, "rev-parse", f"{remote_sha}^{{tree}}") == tree
            and _git(git_dir, "rev-list", "--count", remote_sha) == "1"
        ):
            return False
        # Only the notebooks' names are links handed out.
        previous = {
            name
            for name in _git(git_dir, "ls-tree", "--name-only", remote_sha).splitlines()
            if name.endswith(".ipynb")
        }
    names = {f"{lab_id}.ipynb" for lab_id in published}
    if (removed := sorted(previous - names)) and not break_published_links:
        msg = "would break these published links: " + ", ".join(removed)
        raise LabPublishRefusedError(msg)
    today = datetime.now(tz=UTC).date().isoformat()
    commit = _git(git_dir, "commit-tree", tree, "-m", f"Labs ({today})")
    subprocess.run(
        [
            "git",
            "-C",
            str(git_dir),
            "push",
            f"--force-with-lease={branch}:{remote_sha}",
            remote,
            f"{commit}:refs/heads/{branch}",
        ],
        check=True,
        capture_output=True,
    )
    return True
