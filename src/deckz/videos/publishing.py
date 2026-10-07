"""Replace the videos remote's branch with one commit of every scene's renders.

Each publish force-pushes a single parentless commit, whose tree holds
every scene's render at its site path under the videos directory, plus
`.nojekyll` (for GitHub Pages). The renders themselves aren't committed to
this repo (the videos directory is gitignored): their blobs are written to
the repo's object store on the way, so the repo itself never grows, even
though a replaced render's old blob becomes unreachable. A published
render's URL may already be handed out (e.g. a QR code in a PDF): a
publish refuses to drop one, unless told to.

Shells out to `git` (fetch and push need the user's own credentials/ssh
agent) rather than using pygit2, which deckz otherwise relies on for
read-only repository discovery.
"""

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory

from ..exceptions import VideoPublishRefusedError
from .scenes import Scene, out_of_date, renders


def _git(
    git_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> str:
    return subprocess.run(
        ["git", "-C", str(git_dir), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
        env=env,
    ).stdout.strip()


def site_path(videos_dir: Path, file: Path) -> str:
    return file.relative_to(videos_dir).as_posix()


@dataclass(frozen=True)
class PublishPreview:
    """What `publish` would push, computed ahead of any git or network call."""

    site: dict[str, Path]
    """Each render to publish, by its site path."""
    problems: tuple[str, ...]
    """Why a render isn't ready to publish (missing, stale, over the size limit)."""
    warnings: tuple[str, ...]
    """A render that's publishable, but large enough to flag."""


def publishable(
    found: list[Scene],
    videos_dir: Path,
    *,
    quality: str,
    max_size: int,
    warn_size: int,
) -> PublishPreview:
    """Which of `found`'s renders are ready to publish, at `videos_dir`.

    Args:
        found: Every registered scene (`scenes(settings)`).
        videos_dir: `GlobalPaths.videos_dir`.
        quality: The renders must be at this Manim quality to publish.
        max_size: Refuse a render over this size, in bytes.
        warn_size: Flag, but still publish, a render over this size, in bytes.

    Returns:
        The preview.
    """
    site: dict[str, Path] = {}
    problems = []
    warnings = []
    for scene in found:
        for render in renders(videos_dir, scene):
            path = site_path(videos_dir, render.file)
            if out_of_date(render, quality):
                problems.append(
                    f"{path}: missing, stale or not at quality {quality} "
                    "(run `deckz videos render`)"
                )
                continue
            size = render.file.stat().st_size
            if size > max_size:
                problems.append(f"{path}: over the {max_size // 1_000_000} MB limit")
                continue
            if size > warn_size:
                warnings.append(f"{path} is over {warn_size // 1_000_000} MB")
            site[path] = render.file
    return PublishPreview(site=site, problems=tuple(problems), warnings=tuple(warnings))


def _blob(git_dir: Path, file: Path) -> str:
    return _git(git_dir, "hash-object", "-w", str(file))


def site_tree(git_dir: Path, site: dict[str, Path]) -> str:
    """Store `site`'s files as blobs in `git_dir`'s object store, and their tree.

    Returns:
        The tree's sha, holding each render at its site path plus `.nojekyll`.
    """
    with TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.touch()
        # A scratch index builds the nested tree (`git mktree` is one level).
        env = {**environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        for path, file in sorted({".nojekyll": empty, **site}.items()):
            sha = _blob(git_dir, file)
            _git(
                git_dir,
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{sha},{path}",
                env=env,
            )
        return _git(git_dir, "write-tree", env=env)


def fetch_published(git_dir: Path, remote: str, branch: str) -> str | None:
    """Fetch `remote`'s `branch`, if it already exists.

    Returns:
        The published commit, or None before the first publish.
    """
    if not _git(git_dir, "ls-remote", "--heads", remote, branch):
        return None
    subprocess.run(
        ["git", "-C", str(git_dir), "fetch", "--quiet", remote, branch],
        capture_output=True,
        text=True,
        check=False,
    )
    return _git(git_dir, "rev-parse", f"{remote}/{branch}")


def published_paths(git_dir: Path, commit: str | None) -> set[str]:
    """The site paths a published `commit` holds.

    Returns:
        Each file's path, empty if `commit` is None.
    """
    if commit is None:
        return set()
    return set(_git(git_dir, "ls-tree", "-r", "--name-only", commit).splitlines())


def publish(
    git_dir: Path,
    scenes_dir: Path,
    preview: PublishPreview,
    *,
    remote: str,
    branch: str,
    break_published_links: bool = False,
) -> bool:
    """Replace `remote`'s `branch` with one commit of `preview`'s renders.

    Args:
        git_dir: Root of the deckz-managed repository.
        scenes_dir: `GlobalPaths.scenes_dir`, checked for uncommitted changes.
        preview: A `publishable()` result.
        remote: Git remote to force-push to.
        branch: Branch of `remote` to replace.
        break_published_links: Allow dropping an already-published render's \
            site path.

    Returns:
        True if a new commit was pushed, False if the remote was already \
        up to date.

    Raises:
        VideoPublishRefusedError: If `scenes_dir` has uncommitted changes, \
            `preview` has problems, or the publish would drop an \
            already-published render's site path (unless \
            `break_published_links`).
    """
    scenes_rel = scenes_dir.relative_to(git_dir).as_posix()
    if _git(git_dir, "status", "--porcelain", "--", scenes_rel):
        msg = f"{scenes_rel} has uncommitted changes"
        raise VideoPublishRefusedError(msg)
    if preview.problems:
        raise VideoPublishRefusedError("; ".join(preview.problems))

    remote_commit = fetch_published(git_dir, remote, branch)
    tree = site_tree(git_dir, preview.site)
    if remote_commit is not None:
        if (
            _git(git_dir, "rev-parse", f"{remote_commit}^{{tree}}") == tree
            and _git(git_dir, "rev-list", "--count", remote_commit) == "1"
        ):
            return False
        previous = published_paths(git_dir, remote_commit)
        removed = sorted(previous - set(preview.site) - {".nojekyll"})
        if removed and not break_published_links:
            msg = "would break these published links: " + ", ".join(removed)
            raise VideoPublishRefusedError(msg)

    today = datetime.now(tz=UTC).date().isoformat()
    commit = _git(git_dir, "commit-tree", tree, "-m", f"Videos ({today})")
    subprocess.run(
        [
            "git",
            "-C",
            str(git_dir),
            "push",
            f"--force-with-lease={branch}:{remote_commit or ''}",
            remote,
            f"{commit}:refs/heads/{branch}",
        ],
        check=True,
        capture_output=True,
    )
    return True
