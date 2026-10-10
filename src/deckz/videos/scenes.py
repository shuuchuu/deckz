"""Discover `@register_scene` classes and the renders they're due.

A scene is a Manim `Scene` subclass decorated `@register_scene` (optionally
`languages=(...)`) in a `.py` file under `GlobalPaths.scenes_dir`. Scenes
are found by reading each module's source with `ast`, not by importing it
(Manim is only needed, and only imported, by an actual render, through the
`deckz[videos]` extra) -- so listing or checking scenes never needs it
installed.
"""

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, overload

from ..exceptions import VideoSceneError
from ..models import Lang
from ..stamps import digest, is_fresh, python_sources

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

LANGUAGES: tuple[Lang, ...] = ("fr", "en")
DEFAULT_LANGUAGE: Lang = "fr"


@dataclass(frozen=True)
class Scene:
    """One `@register_scene` class."""

    module: Path
    name: str
    """The class name, e.g. `CausalMask`."""
    video: str
    """The video's path, e.g. `nn/causal-mask` (the module's path, without \
    its own name, plus the class name, kebab-cased)."""
    languages: tuple[Lang, ...]
    """Languages the scene has on-screen text for; empty if it has none \
    (one render for every language)."""
    import_root: Path | None = None
    """The directory the module's absolute imports resolve against \
    (`scenes_dir`'s parent, see `rendering.render_one`), for `sources`."""

    def sources(self) -> tuple[Path, ...]:
        """The files its renders are made from, which their stamps cover.

        Returns:
            Its module, then the modules under `import_root` it imports, \
            transitively (`deckz.stamps.python_sources`).
        """
        roots = (self.module.parent,)
        if self.import_root is not None:
            roots += (self.import_root,)
        return python_sources(self.module, roots)


@dataclass(frozen=True)
class Render:
    """One render a `Scene` is due, one per its `languages` (or one if none)."""

    scene: Scene
    language: Lang | None
    file: Path


@overload
def register_scene[T: type](scene: T, /) -> T: ...


@overload
def register_scene[T: type](
    *, languages: tuple[Lang, ...] = ()
) -> Callable[[T], T]: ...


def register_scene[T: type](
    scene: T | None = None, /, *, languages: tuple[Lang, ...] = ()
) -> T | Callable[[T], T]:
    """Mark a Manim `Scene` subclass under `scenes_dir` as a video to render.

    A marker only: `deckz videos` finds decorated classes by reading the
    module's source (see the module docstring), and renders them. A scene
    with on-screen text lists its `languages` (`("fr", "en")`): it's
    rendered once per language, with `SLIDES_VIDEO_LANG`-style env var
    (`deckz.videos.rendering`'s `LANG_ENV_VAR`) set to the one to show.

    Returns:
        `scene`, unchanged (or a decorator returning it, given `languages`).
    """
    del languages  # Read from the source, see `scenes()`.
    if scene is None:
        return lambda scene: scene
    return scene


def _languages(call: ast.Call | None, where: str) -> tuple[Lang, ...]:
    if call is None:
        return ()
    if call.args or any(k.arg != "languages" for k in call.keywords):
        msg = f"{where}: register_scene only takes `languages=(...)`"
        raise VideoSceneError(msg)
    if not call.keywords:
        return ()
    languages = ast.literal_eval(call.keywords[0].value)
    if not (
        isinstance(languages, tuple)
        and languages
        and set(languages) <= set(LANGUAGES)
        and len(set(languages)) == len(languages)
    ):
        msg = f"{where}: languages must be a tuple of distinct {LANGUAGES}"
        raise VideoSceneError(msg)
    return languages


def scenes(settings: "GlobalSettings") -> list[Scene]:
    """Every registered scene under `settings.paths.scenes_dir`.

    A `register_scene` call that isn't a plain `languages=(...)` of known
    languages raises `VideoSceneError`.

    Returns:
        The scenes, sorted by module.
    """
    scenes_dir = settings.paths.scenes_dir
    found = []
    for module in sorted(scenes_dir.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf8"), filename=str(module))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call else decorator
                if not (isinstance(target, ast.Name) and target.id == "register_scene"):
                    continue
                languages = _languages(call, f"{module}:{node.lineno}")
                name = re.sub(r"(?<!^)(?=[A-Z])", "-", node.name).lower()
                path = module.parent.relative_to(scenes_dir) / name
                found.append(
                    Scene(
                        module,
                        node.name,
                        path.as_posix(),
                        languages,
                        scenes_dir.parent,
                    )
                )
    return found


def _render_file(videos_dir: Path, scene: Scene, language: Lang | None) -> Path:
    path = Path(scene.video)
    if language in (None, DEFAULT_LANGUAGE):
        return videos_dir / path.with_suffix(".mp4")
    return videos_dir / path.parent / language / f"{path.name}.mp4"


def renders(videos_dir: Path, scene: Scene) -> list[Render]:
    """The renders `scene` is due: one per language, or one if it has no text.

    Returns:
        Each render, its language (`None` for every language) and file.
    """
    languages = scene.languages or (None,)
    return [
        Render(scene, lang, _render_file(videos_dir, scene, lang)) for lang in languages
    ]


def video_file(settings: "GlobalSettings", video: str, language: Lang) -> Path:
    """The render a `language` deck shows for `video` (a theme's filter uses this).

    Returns:
        The render's mp4 under `settings.paths.videos_dir` (which may not \
        exist yet).

    Raises:
        LookupError: If no scene renders `video`, or not in `language`.
    """
    scene = next((s for s in scenes(settings) if s.video == video), None)
    if scene is None:
        msg = f"no scene under {settings.paths.scenes_dir} renders the video {video!r}"
        raise LookupError(msg)
    if not scene.languages:
        return settings.paths.videos_dir / f"{video}.mp4"
    if language not in scene.languages:
        msg = (
            f"{scene.name} ({scene.module}) has on-screen text in "
            f"{', '.join(scene.languages)} only, not {language}: add it to its "
            "`register_scene(languages=...)`"
        )
        raise LookupError(msg)
    return _render_file(settings.paths.videos_dir, scene, language)


def quality(file: Path) -> str | None:
    """The quality `file` was rendered at.

    Returns:
        Its `.quality` stamp, or None if it has none.
    """
    stamp = file.with_suffix(".quality")
    return stamp.read_text(encoding="utf8").strip() if stamp.is_file() else None


def out_of_date(render: Render, wanted: str) -> bool:
    """Whether `render` must be (re-)rendered at quality `wanted`.

    Returns:
        True if it or its poster is missing, if its stamp (`deckz.stamps`) \
        doesn't match its scene's sources, or if it's at another quality.
    """
    file = render.file
    sources = render.scene.sources()
    return (
        not file.with_suffix(".png").is_file()
        or not is_fresh(file, digest(sources), sources)
        or quality(file) != wanted
    )
