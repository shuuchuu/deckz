"""Replace the labs remote's branch with one commit of the published notebooks.

Each publish force-pushes a single parentless commit, whose tree holds every
notebook committed under the configured notebooks directory, as
`<id>.ipynb`, and nothing else: trainees see the current notebooks only,
never their history (kept in this repo) nor where a notebook sits in it. A
published name may already be in PDFs handed to trainees, so a publish
refuses to drop any name the remote branch already has, unless told to.

Shells out to `git` (fetch and push need the user's own credentials/ssh
agent, which `git` already picks up from the environment) rather than using
pygit2, which deckz otherwise relies on for read-only repository discovery.
"""

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ..exceptions import LabPublishRefusedError


def _git(git_dir: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(git_dir), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
    ).stdout.strip()


def _metadata_id(metadata: dict[str, object], key: str) -> str:
    value: object = metadata
    for part in key.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, str) else ""


def _published_notebooks(
    git_dir: Path, notebooks_dir: Path, *, id_metadata_key: str, id_pattern: str
) -> dict[str, str]:
    """The notebooks committed at HEAD, by ID.

    Returns:
        The blob sha of each ID's notebook.

    Raises:
        LabPublishRefusedError: If a committed notebook has no valid ID, or \
            two notebooks share one.
    """
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
        metadata = json.loads(_git(git_dir, "cat-file", "blob", sha))["metadata"]
        lab_id = _metadata_id(metadata, id_metadata_key)
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


def publish(
    git_dir: Path,
    notebooks_dir: Path,
    *,
    id_metadata_key: str,
    id_pattern: str,
    remote: str,
    branch: str,
    break_published_links: bool = False,
) -> bool:
    """Replace `remote`'s `branch` with one commit of HEAD's lab notebooks.

    Returns:
        True if a new commit was pushed, False if the remote was already up \
        to date.

    Raises:
        LabPublishRefusedError: If the notebooks directory has uncommitted \
            changes, a committed notebook has no valid or unique ID, or the \
            publish would drop an already-published notebook (unless \
            `break_published_links`).
    """
    notebooks_rel = notebooks_dir.relative_to(git_dir).as_posix()
    if _git(git_dir, "status", "--porcelain", "--", notebooks_rel):
        msg = f"{notebooks_rel} has uncommitted changes"
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
        git_dir, notebooks_dir, id_metadata_key=id_metadata_key, id_pattern=id_pattern
    )
    tree = _git(
        git_dir,
        "mktree",
        stdin="".join(
            f"100644 blob {sha}\t{lab_id}.ipynb\n"
            for lab_id, sha in sorted(published.items())
        ),
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
        previous = set(
            _git(git_dir, "ls-tree", "-r", "--name-only", remote_sha).splitlines()
        )
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
