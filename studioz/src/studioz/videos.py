"""The workspace's videos, and their renders as of the last commit.

What deckz says of them comes from the workspace's own `deckz videos list
--json` (under a second): the state of each render (never rendered, stale, a
draft, or fresh at the published quality), the scene's module and the
sources its renders are made from.

Renders aren't committed (they're published apart, `deckz videos publish`),
so the render as of the last commit, for the before/after, is one studioz
kept: whenever it lists the videos, a render up to date with its scene's
sources, none of which changed since the last commit, is the commit's, and
is kept (a hard link) under `.run/studioz/videos/<key>/`, the key naming the
sources' blobs at the last commit (so a commit leaving the scene alone keeps
it). A render made before studioz first saw the scene unchanged has none: its
before/after says so.
"""

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident

from deckz.models import Lang

from .background import changes, git
from .watches import workspace_environment
from .workspaces import STATE_DIR

BASELINES_DIR = STATE_DIR / "videos"
"""Relative to a workspace."""

STATES = {
    "missing": "jamais rendue",
    "stale": "à rendre",
    "draft": "brouillon",
    "fresh": "à jour",
}
"""`deckz videos list`'s states, in French, the most pressing first."""

DRAFT_QUALITY = "l"
"""Manim's quickest quality (480p15), for a draft."""

_TIMEOUT = 60


@dataclass(frozen=True)
class Render:
    language: Lang | None
    """None for a scene with no on-screen text: one render for every language."""
    file: str
    """Relative to the workspace, as every path here."""
    poster: str
    quality: str | None
    state: str
    """A key of `STATES`."""


@dataclass(frozen=True)
class Video:
    """A scene and its renders."""

    video: str
    """Its path, e.g. `nn/causal-mask`, as deckz names it."""
    scene: str
    """Its class."""
    module: str
    line: int
    sources: tuple[str, ...]
    renders: tuple[Render, ...]

    @property
    def state(self) -> str:
        """Its most pressing render's state."""
        return min((r.state for r in self.renders), key=list(STATES).index)

    @property
    def languages(self) -> tuple[Lang, ...]:
        return tuple(r.language for r in self.renders if r.language)

    def render(self, lang: Lang) -> Render:
        """The render a `lang` deck shows.

        Returns:
            The one in `lang`, or the only one of a scene with no text.
        """
        return next((r for r in self.renders if r.language == lang), self.renders[0])


@dataclass(frozen=True)
class Listing:
    published_quality: str
    videos: tuple[Video, ...]
    error: str | None = None
    """Why deckz couldn't list them."""

    def find(self, video: str) -> Video | None:
        return next((v for v in self.videos if v.video == video), None)

    def folders(self) -> dict[str, list[Video]]:
        """The videos by folder (`nn` for `nn/causal-mask`), in deckz's order.

        Returns:
            Each folder's videos.
        """
        found: dict[str, list[Video]] = {}
        for video in self.videos:
            found.setdefault(video.video.rpartition("/")[0], []).append(video)
        return found


def listing(workspace: Path) -> Listing:
    """The workspace's videos, as its own deckz lists them.

    Returns:
        Each scene and its renders, in deckz's order, or why it failed.
    """
    try:
        result = subprocess.run(
            [str(workspace / ".venv" / "bin" / "deckz"), "videos", "list", "--json"],
            cwd=workspace,
            env=workspace_environment(workspace),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Listing("", (), str(error))
    try:
        found = json.loads(result.stdout)
        videos: dict[str, Video] = {}
        for entry in found["renders"]:
            render = Render(
                entry["language"],
                entry["file"],
                entry["poster"],
                entry["quality"],
                entry["state"],
            )
            known = videos.get(entry["video"])
            videos[entry["video"]] = Video(
                entry["video"],
                entry["scene"],
                entry["module"],
                entry["line"],
                tuple(entry["sources"]),
                (*(known.renders if known else ()), render),
            )
        return Listing(found["published_quality"], tuple(videos.values()))
    except (ValueError, KeyError, TypeError):
        lines = (result.stderr or result.stdout).strip().splitlines()
        error = lines[-1] if lines else f"code {result.returncode}"
        return Listing("", (), error.replace(f"{workspace}/", ""))


def _key(workspace: Path, video: Video) -> str | None:
    """What names the scene's sources as of the last commit.

    Returns:
        A digest of their blobs at `HEAD`, None if one isn't committed.
    """
    tree = git(workspace, "ls-tree", "HEAD", "--", *video.sources)
    if tree is None or len(tree.splitlines()) != len(video.sources):
        return None
    return hashlib.sha256(tree.encode()).hexdigest()[:16]


def baseline(workspace: Path, video: Video, render: Render) -> Path | None:
    """The render as of the last commit, if studioz kept it.

    Returns:
        Its copy, None if none was kept.
    """
    key = _key(workspace, video)
    if key is None:
        return None
    path = workspace / BASELINES_DIR / key / render.file
    return path if path.is_file() else None


def unchanged(workspace: Path, video: Video) -> bool:
    """Whether none of the scene's sources changed since the last commit.

    Returns:
        True if `git status` lists none of them.
    """
    changed = {change.path for change in changes(workspace)}
    return not changed & set(video.sources)


def _keep(render: Path, kept: Path) -> None:
    """Keep `render` as `kept`: a hard link, a copy where links can't be made.

    deckz moves each new render into place, never writing over the previous
    one (`deckz.videos.rendering`): the link keeps it.
    """
    if kept.is_file() and kept.samefile(render):
        return
    kept.parent.mkdir(parents=True, exist_ok=True)
    # Its own name: two pages may list the videos at once.
    partial = kept.with_name(f".{kept.name}.{os.getpid()}-{get_ident()}.partial")
    try:
        os.link(render, partial)
    except OSError:
        shutil.copy2(render, partial)
    partial.replace(kept)


def keep_baselines(workspace: Path, found: Listing) -> None:
    """Copy each render that is the last commit's, and drop the others' copies.

    A render is the last commit's when it's up to date with its scene's
    sources (a draft or fresh) and none of them changed since the commit.
    """
    if found.error:
        return
    changed = {change.path for change in changes(workspace)}
    root = workspace / BASELINES_DIR
    kept = set()
    for video in found.videos:
        key = _key(workspace, video)
        if key is None:
            continue
        kept.add(key)
        if changed & set(video.sources):
            continue
        for render in video.renders:
            if render.state in {"draft", "fresh"}:
                _keep(workspace / render.file, root / key / render.file)
    if root.is_dir():
        for directory in root.iterdir():
            if directory.name not in kept:
                shutil.rmtree(directory, ignore_errors=True)


def served(workspace: Path, file: str, videos_dir: Path) -> Path | None:
    """The workspace's render or poster `file`, or a copy studioz kept.

    Args:
        workspace: The workspace.
        file: The file, relative to it.
        videos_dir: The renders' directory, relative to it.

    Returns:
        Its path, None unless it's an existing `.mp4` or `.png` under \
        `videos_dir` or `BASELINES_DIR`.
    """
    relative = Path(file)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if relative.suffix not in {".mp4", ".png"}:
        return None
    if not (
        relative.is_relative_to(videos_dir) or relative.is_relative_to(BASELINES_DIR)
    ):
        return None
    path = workspace / relative
    return path if path.is_file() else None


def render_steps(workspace: Path, video: str, quality: str) -> list[list[str]]:
    """`deckz videos render` of one scene (every language), its quality spelled out.

    Returns:
        The job's one step, to run in the workspace.
    """
    deckz = str(workspace / ".venv" / "bin" / "deckz")
    return [[deckz, "videos", "render", video, "--quality", quality]]
