"""Render `Scene`s with Manim, and their poster frame with ffmpeg.

Each render is its own process: `sys.executable -m manim` (so it runs in
deckz's own environment, needing the `deckz[videos]` extra) and `ffmpeg`
(an external binary, as poppler is for `deckz check overflow`). Nothing
here imports Manim itself.
"""

import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from os import cpu_count, environ, pathsep
from pathlib import Path
from shutil import copyfile
from subprocess import run
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ..exceptions import MissingExtraError
from .scenes import DEFAULT_LANGUAGE, Render

if TYPE_CHECKING:
    from ..components.protocols import ProgressReporterProtocol

LANG_ENV_VAR = "SLIDES_VIDEO_LANG"
"""Env var a scene's `construct()` reads to pick its on-screen text's language."""


def ensure_manim_installed() -> None:
    """Raise early if Manim isn't installed, instead of failing deep in a subprocess.

    Raises:
        MissingExtraError: If Manim isn't importable.
    """
    if find_spec("manim") is None:
        msg = 'manim is not installed, install it with `pip install "deckz[videos]"`'
        raise MissingExtraError(msg)


def render_one(render: Render, quality: str, scenes_dir: Path) -> str | None:
    """Render one video and its poster frame, and stamp its quality.

    Returns:
        An error message, or None if it succeeded.
    """
    scene, language, video = render.scene, render.language, render.file
    label = f"{scene.video}" + (f" ({language})" if language else "")
    with TemporaryDirectory() as media_dir:
        env = {
            **environ,
            # A scene module may import other repo-specific modules under
            # `scenes_dir`'s parent (e.g. shared assets-builder helpers).
            "PYTHONPATH": pathsep.join(
                [str(scenes_dir.parent), environ.get("PYTHONPATH", "")]
            ),
            LANG_ENV_VAR: language or DEFAULT_LANGUAGE,
        }
        completed = run(
            [
                sys.executable,
                "-m",
                "manim",
                "render",
                f"-q{quality}",
                "--media_dir",
                media_dir,
                "--progress_bar",
                "none",
                "--disable_caching",
                "-v",
                "WARNING",
                "-o",
                video.stem,
                str(scene.module),
                scene.name,
            ],
            cwd=scene.module.parent,
            env=env,
            capture_output=True,
            encoding="utf8",
            check=False,
        )
        rendered = next(Path(media_dir).rglob(f"{video.stem}.mp4"), None)
        if completed.returncode != 0 or rendered is None:
            return f"{label}: {completed.stderr.strip()[-2000:]}"
        video.parent.mkdir(parents=True, exist_ok=True)
        copyfile(rendered, video)
    poster = run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-sseof",
            "-0.1",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(video.with_suffix(".png")),
        ],
        capture_output=True,
        encoding="utf8",
        check=False,
    )
    if poster.returncode != 0:
        return f"{label}: no poster frame: {poster.stderr.strip()}"
    video.with_suffix(".quality").write_text(quality, encoding="utf8")
    return None


def render_all(
    to_render: Iterable[Render],
    quality: str,
    scenes_dir: Path,
    progress: "ProgressReporterProtocol | None" = None,
) -> list[str]:
    """Render every one of `to_render`, in parallel.

    Raises `MissingExtraError` first if Manim isn't installed.

    Args:
        to_render: The renders to do.
        quality: Manim quality flag (`l`, `m`, `h`, `p` or `k`).
        scenes_dir: `GlobalPaths.scenes_dir`, put on `PYTHONPATH` for the \
            render subprocess (see `render_one`).
        progress: Advanced once per finished render (success or failure).

    Returns:
        One error message per failed render, empty if they all succeeded.
    """
    from ..components.progress import NullProgress

    to_render = list(to_render)
    if not to_render:
        return []
    ensure_manim_installed()
    progress = progress if progress is not None else NullProgress()
    failed = []
    # Each render is its own process (manim, then ffmpeg): threads are enough.
    with (
        ThreadPoolExecutor(max(1, (cpu_count() or 2) // 2)) as pool,
        progress.track("Rendering videos…", len(to_render)) as advance,
    ):
        for error in pool.map(lambda r: render_one(r, quality, scenes_dir), to_render):
            if error:
                failed.append(error)
            advance()
    return failed
