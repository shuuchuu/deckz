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
from ..remotes import branch_tip, replace_branch


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


def _is_tree(git_dir: Path, tip: str | None, tree: str) -> bool:
    # The tip is already one parentless commit of this tree.
    return bool(tip) and (
        _git(git_dir, "rev-parse", f"{tip}^{{tree}}") == tree
        and _git(git_dir, "rev-list", "--count", tip) == "1"
    )


def _replace(
    git_dir: Path,
    tree: str,
    *,
    remote: str,
    branch: str,
    tip: str | None,
    message: str,
) -> None:
    commit = _git(git_dir, "commit-tree", tree, "-m", message)
    replace_branch(git_dir, remote, branch, commit, tip)


def publish(
    git_dir: Path,
    notebooks_dir: Path,
    *,
    published_dir: Path | None = None,
    id_metadata_key: str,
    id_pattern: str,
    remote: str,
    branch: str,
    files_remote: str | None = None,
    files_branch: str = "main",
    break_published_links: bool = False,
    not_secrets: Iterable[str] = (),
) -> bool:
    """Replace `remote`'s `branch` with one commit of HEAD's lab notebooks.

    The files committed under `published_dir` go into the same commit, at
    the same paths, or, given a `files_remote`, into a commit of their own
    that replaces its `files_branch` (e.g. a repository a Codespace opens,
    holding no notebook).

    Returns:
        True if a new commit was pushed, False if the remotes were already \
        up to date.

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
    tip = branch_tip(git_dir, remote, branch)
    published = _published_notebooks(
        git_dir,
        notebooks_dir,
        id_metadata_key=id_metadata_key,
        id_pattern=id_pattern,
        not_secrets=not_secrets,
    )
    files = _published_files(git_dir, published_dir)
    notebooks = {
        f"{lab_id}.ipynb": f"100644 blob {sha}" for lab_id, sha in published.items()
    }
    tree = _tree(git_dir, notebooks if files_remote else {**files, **notebooks})
    # Only the notebooks' names are links handed out.
    previous = {
        name
        for name in (
            _git(git_dir, "ls-tree", "--name-only", tip).splitlines() if tip else []
        )
        if name.endswith(".ipynb")
    }
    if (removed := sorted(previous - notebooks.keys())) and not break_published_links:
        msg = "would break these published links: " + ", ".join(removed)
        raise LabPublishRefusedError(msg)
    today = datetime.now(tz=UTC).date().isoformat()
    pushed = False
    if not _is_tree(git_dir, tip, tree):
        _replace(
            git_dir,
            tree,
            remote=remote,
            branch=branch,
            tip=tip,
            message=f"Labs ({today})",
        )
        pushed = True
    if files_remote:
        files_tip = branch_tip(git_dir, files_remote, files_branch)
        files_tree = _tree(git_dir, files)
        if not _is_tree(git_dir, files_tip, files_tree):
            _replace(
                git_dir,
                files_tree,
                remote=files_remote,
                branch=files_branch,
                tip=files_tip,
                message=f"Published files ({today})",
            )
            pushed = True
    return pushed
