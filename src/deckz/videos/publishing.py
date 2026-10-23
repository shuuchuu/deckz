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
from os import environ, utime
from pathlib import Path
from tempfile import TemporaryDirectory

from ..exceptions import VideoFetchError, VideoPublishRefusedError
from ..remotes import branch_tip, replace_branch
from ..stamps import stamp_path
from .scenes import Scene, out_of_date, quality, renders, state


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


def differing_sources(
    git_dir: Path, scenes_dir: Path, found: list[Scene], commit: str
) -> list[str]:
    """The scenes' sources that differ between the working tree and `commit`.

    A render is fresh for the sources it was made from (its stamp): when
    they're `commit`'s, a render fresh here is fresh for `commit` too.

    Args:
        git_dir: Root of the deckz-managed repository.
        scenes_dir: `GlobalPaths.scenes_dir`: a scene `commit` has and the \
            working tree doesn't counts too.
        found: Every registered scene (`scenes(settings)`).
        commit: The commit to compare with (the upstream branch's).

    Returns:
        Their paths, relative to `git_dir`, sorted.
    """
    sources = sorted(
        {
            source.relative_to(git_dir).as_posix()
            for scene in found
            for source in scene.sources()
        }
    )
    here = (
        dict(
            zip(
                sources,
                _git(
                    git_dir, "hash-object", "--stdin-paths", stdin="\n".join(sources)
                ).splitlines(),
                strict=True,
            )
        )
        if sources
        else {}
    )
    there = {}
    if sources:
        for line in _git(git_dir, "ls-tree", "-r", commit, "--", *sources).splitlines():
            info, path = line.split("\t", 1)
            there[path] = info.split()[2]
    differ = {path for path in sources if here[path] != there.get(path)}
    scenes_rel = scenes_dir.relative_to(git_dir).as_posix()
    changed = _git(git_dir, "diff", "--name-only", commit, "--", scenes_rel)
    differ |= {path for path in changed.splitlines() if path.endswith(".py")}
    return sorted(differ)


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
    return branch_tip(git_dir, remote, branch)


def published_paths(git_dir: Path, commit: str | None) -> set[str]:
    """The site paths a published `commit` holds.

    Returns:
        Each file's path, empty if `commit` is None.
    """
    if commit is None:
        return set()
    return set(_git(git_dir, "ls-tree", "-r", "--name-only", commit).splitlines())


def published_blobs(git_dir: Path, commit: str | None) -> dict[str, str]:
    """The blob of each file a published `commit` holds.

    Returns:
        Each file's blob sha, by its site path; empty if `commit` is None.
    """
    if commit is None:
        return {}
    blobs = {}
    for line in _git(git_dir, "ls-tree", "-r", commit).splitlines():
        info, path = line.split("\t", 1)
        blobs[path] = info.split()[2]
    return blobs


def unpublished_reason(
    git_dir: Path,
    videos_dir: Path,
    file: Path,
    published: dict[str, str],
    *,
    wanted_quality: str,
) -> str | None:
    """What keeps the render `file` from being the published one.

    Args:
        git_dir: Root of the repository (its git computes the render's blob).
        videos_dir: `GlobalPaths.videos_dir`.
        file: The render, under `videos_dir`.
        published: `published_blobs` of the published commit.
        wanted_quality: The quality a published render is at.

    Returns:
        The problem, or None if `file` is published exactly as rendered.
    """
    site = site_path(videos_dir, file)
    if site not in published:
        return f"{site} is not published"
    if not file.is_file():
        return f"{site} is not rendered"
    if quality(file) != wanted_quality:
        return f"{site} is a draft render"
    if _git(git_dir, "hash-object", str(file)) != published[site]:
        return f"{site} differs from its published version"
    return None


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
    replace_branch(git_dir, remote, branch, commit, remote_commit)
    return True


@dataclass(frozen=True)
class FetchResult:
    """What `fetch_renders` put in place, and what it couldn't."""

    fetched: tuple[Path, ...]
    """The renders written, each with its poster."""
    unpublished: tuple[str, ...]
    """The site paths of the missing renders nothing published yet."""
    failed: tuple[str, ...]
    """Why a render was written without its poster."""


def fetch_renders(
    git_dir: Path,
    videos_dir: Path,
    found: list[Scene],
    *,
    source: str,
    branch: str,
    quality: str,
) -> FetchResult:
    """Put the published renders in place of the missing ones.

    For a checkout that never rendered them (a CI job, a contributor
    without Manim): each render missing from `videos_dir` is written from
    `source`'s `branch` (a remote's name or a repository's URL), with its
    poster frame (ffmpeg) and its `quality` stamp, the published one. A
    render already there is never replaced, and one up to date in another
    checkout of the repository is copied from there instead
    (`deckz.stamps.adopt`). Nothing knows which sources a
    published render was made from, so a fetched one carries no sources
    stamp, and is dated to the epoch: `deckz videos render` takes it for
    stale and renders it again.

    Args:
        git_dir: The repository, whose object store receives the fetch.
        videos_dir: `GlobalPaths.videos_dir`.
        found: Every registered scene (`scenes(settings)`).
        source: The remote, or URL, to fetch from.
        branch: The branch the renders are published on.
        quality: `videos.published_quality`.

    Returns:
        What was fetched, and what wasn't.

    Raises:
        VideoFetchError: If `source` can't be fetched.
    """
    from .rendering import make_poster

    missing = [
        render
        for scene in found
        for render in renders(videos_dir, scene)
        if not render.file.is_file() and state(render, quality) == "missing"
    ]
    if not missing:
        return FetchResult((), (), ())
    fetched = subprocess.run(
        ["git", "-C", str(git_dir), "fetch", "--quiet", source, branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode:
        msg = (
            f"can't fetch {branch} from {source}: {fetched.stderr.strip()}"
            " (`videos.publish_remote` names the remote, or pass its URL)"
        )
        raise VideoFetchError(msg)
    published = published_blobs(git_dir, _git(git_dir, "rev-parse", "FETCH_HEAD"))
    written, unpublished, failed = [], [], []
    for render in missing:
        path = site_path(videos_dir, render.file)
        if (blob := published.get(path)) is None:
            unpublished.append(path)
            continue
        content = subprocess.run(
            ["git", "-C", str(git_dir), "cat-file", "blob", blob],
            capture_output=True,
            check=True,
        ).stdout
        render.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = render.file.with_name(f".{render.file.name}.part")
        temporary.write_bytes(content)
        # Dated to the epoch: `is_fresh` takes an unstamped render newer than
        # its sources for up to date, which a fetched one may not be.
        utime(temporary, (0, 0))
        # A stamp left by a render since deleted isn't about this one.
        stamp_path(render.file).unlink(missing_ok=True)
        temporary.replace(render.file)  # Never half a video.
        if error := make_poster(render.file):
            failed.append(f"{path}: {error}")
            continue
        render.file.with_suffix(".quality").write_text(quality, encoding="utf8")
        written.append(render.file)
    return FetchResult(tuple(written), tuple(unpublished), tuple(failed))
