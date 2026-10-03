"""Provide general utility functions that would not fit in other modules."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from multiprocessing import get_context
from multiprocessing.pool import Pool
from pathlib import Path, PurePosixPath
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import DeckSettings
    from .models import Lang, Node, ResolvedDeck

# Modules loaded by `import_module_from_path`, keyed by what makes a reload
# necessary: a long-lived process (`--watch`) reuses an unchanged module --
# and whatever it memoizes at module level -- across builds, but still picks
# up an edit to it.
_path_modules: dict[tuple[Path, int, str], ModuleType] = {}
_path_modules_lock = Lock()


def file_changed(original: Path, copy: Path) -> bool:
    """Whether `copy` is missing or differs from `original` in content.

    Returns:
        True if `copy` needs updating.
    """
    from filecmp import cmp

    return not (copy.is_file() and cmp(original, copy, shallow=False))


def copy_file_if_changed(original: Path, copy: Path) -> bool:
    """Copy `original` to `copy` unless `copy` already has the same content.

    Content, not modification time, decides: a `git checkout` restoring an \
    older file, or a `touch`, then neither skips nor forces a copy.

    Args:
        original: Path of the file that you want to copy.
        copy: Path of the destination.

    Returns:
        True if the file was copied, False if it wasn't needed.
    """
    from shutil import copyfile

    if not file_changed(original, copy):
        return False
    copy.parent.mkdir(parents=True, exist_ok=True)
    copyfile(original, copy)
    return True


def sync_tree(files: Mapping[PurePosixPath, Path], destination: Path) -> None:
    """Make `destination` hold exactly `files`, copying only what changed.

    Args:
        files: Source file of each path to create, relative to `destination`.
        destination: Directory to sync. Files in it not in `files` are \
            removed, and so are the directories left empty.
    """
    if destination.exists() and not destination.is_dir():
        destination.unlink()
    for relative, source in files.items():
        copy_file_if_changed(source, destination / relative)
    if not destination.is_dir():
        destination.mkdir(parents=True)
        return
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            if not any(path.iterdir()):
                path.rmdir()
        elif PurePosixPath(path.relative_to(destination).as_posix()) not in files:
            path.unlink()


def import_module_from_path(path: Path, name: str) -> ModuleType:
    """Import a module from its file path, without it needing to be on `sys.path`.

    Used to load a Python module a target repo supplies by filesystem \
    convention (e.g. `templates/jinja2/env.py`, `templates/assets_builders.py`) \
    rather than as an installed/importable package. Memoized for as long as \
    the file is unmodified.

    Args:
        path: Path to the module's `.py` file.
        name: Name to register the loaded module under (only used internally \
            by the import machinery, does not need to be importable itself).

    Returns:
        The imported module.

    Raises:
        DeckzError: If `path` does not exist or cannot be loaded as a module.
    """
    from importlib.util import module_from_spec, spec_from_file_location

    from .exceptions import DeckzError

    if not path.is_file():
        msg = f"could not find a Python module at {path}"
        raise DeckzError(msg)
    key = (path.resolve(), path.stat().st_mtime_ns, name)
    with _path_modules_lock:
        if key in _path_modules:
            return _path_modules[key]
        spec = spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            msg = f"could not load {path} as a module"
            raise DeckzError(msg)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        _path_modules[key] = module
        return module


def import_module_and_submodules(package_name: str) -> None:
    """Import all modules and submodules from a package.

    From https://github.com/allenai/allennlp/blob/master/allennlp/common/util.py.

    Args:
        package_name: Name of the package to fully import.
    """
    from importlib import import_module, reload
    from importlib import invalidate_caches as importlib_invalidate_caches
    from pkgutil import walk_packages
    from sys import modules

    importlib_invalidate_caches()

    if package_name in modules:
        module = modules[package_name]
        reload(module)
    else:
        module = import_module(package_name)
    path = getattr(module, "__path__", [])
    path_string = "" if not path else path[0]

    for module_finder, name, _ in walk_packages(path):
        if (
            path_string
            and hasattr(module_finder, "path")
            and module_finder.path != path_string
        ):
            continue
        subpackage = f"{package_name}.{name}"
        import_module_and_submodules(subpackage)


def dirs_hierarchy(
    git_dir: Path, user_config_dir: Path, current_dir: Path
) -> Iterator[Path]:
    from itertools import islice

    yield git_dir
    yield user_config_dir
    if current_dir.is_relative_to(git_dir):
        yield from islice(intermediate_dirs(git_dir, current_dir), 1, None)
    else:
        yield current_dir


def intermediate_dirs(start: Path, end: Path) -> Iterator[Path]:
    start = start.resolve()
    yield start
    for part in end.resolve().relative_to(start).parts:
        start /= part
        yield start


def get_git_dir(path: Path) -> Path:
    """Search and resolve the path of the git dir containing the path given as argument.

    Args:
        path: Path contained in the git dir to search for.

    Returns:
        Resolved path to the git repository containing the path given as argument.

    Raises:
        GitRepositoryNotFoundError: Raised if no git repository is found in the path \
            ancestors.
    """
    from pygit2 import Repository, discover_repository

    from deckz.exceptions import GitRepositoryNotFoundError

    repository = discover_repository(str(path))
    if repository is None:
        msg = "could not find the path of the current git working directory"
        raise GitRepositoryNotFoundError(msg)
    return Path(Repository(repository).workdir).resolve()


def load_yaml(path: Path) -> Any:
    from yaml import YAMLError, safe_load

    from .exceptions import InvalidConfigurationError

    try:
        return safe_load(path.read_text(encoding="utf8"))
    except (YAMLError, UnicodeDecodeError) as e:
        msg = f"{path} is not valid YAML:\n{e}"
        raise InvalidConfigurationError(msg) from e


def load_all_yamls(paths: Iterable[Path]) -> Iterator[Any]:
    for path in paths:
        with suppress(FileNotFoundError):
            yield load_yaml(path)


def _parse_deck(settings: "DeckSettings", lang: "Lang") -> tuple[Path, "ResolvedDeck"]:
    from .components.factory import DeckSettingsFactory
    from .configuring.variables import get_variables, resolve_variables
    from .exceptions import DeckParsingError

    # A translation gap must not hide the rest of an en deck from analyses.
    parser = DeckSettingsFactory(settings, lang=lang, lenient=lang != "fr").parser()
    try:
        deck = parser.from_deck_definition(settings.paths.deck_definition)
    except DeckParsingError as e:
        if lang == "fr":
            raise
        deck = replace(
            e.deck,
            parts={
                name: replace(part, nodes=_without_unresolved_files(part.nodes))
                for name, part in e.deck.parts.items()
            },
        )
    variables = get_variables(settings, lang, lenient=lang != "fr")
    return (
        settings.paths.deck_definition.parent.relative_to(settings.paths.git_dir),
        resolve_variables(deck, {**variables, "lang": lang}),
    )


def _without_unresolved_files(nodes: Iterable["Node"]) -> tuple["Node", ...]:
    from .models import File, Section

    return tuple(
        replace(node, nodes=_without_unresolved_files(node.nodes))
        if isinstance(node, Section)
        else node
        for node in nodes
        if not (isinstance(node, File) and node.parsing_error is not None)
    )


def all_decks(git_dir: Path, lang: "Lang" = "fr") -> dict[Path, "ResolvedDeck"]:
    """Parse every deck of the repository, with variables resolved as in a build.

    Args:
        git_dir: Root of the repository.
        lang: Language to resolve the decks in. Under "en", files resolve \
            exactly as with `--en`, except a file with no `en/` counterpart \
            is left out of the tree instead of failing the parse, so \
            analyses see every translation that does exist.

    Returns:
        The parsed decks, keyed by their directory relative to `git_dir`.
    """
    from functools import partial

    with create_pool() as pool:
        return dict(
            pool.map(partial(_parse_deck, lang=lang), list(all_deck_settings(git_dir)))
        )


def all_deck_settings(git_dir: Path) -> Iterator["DeckSettings"]:
    """Yield the settings of every deck found recursively under the git directory.

    Each deck's own settings are loaded (a deck directory may have its own \
    `deckz.yml`), but the repository root is `git_dir`, not rediscovered.

    Yields:
        Settings of each deck found.
    """
    from .configuring.settings import DeckSettings

    for targets_path in git_dir.rglob("deck.yml"):
        # Skip hidden directories: build directories (`.build`, `.run`) can
        # hold a deck.yml (e.g. a symlink to their deck's), and aren't decks.
        if any(
            part.startswith(".")
            for part in targets_path.relative_to(git_dir).parent.parts
        ):
            continue
        yield DeckSettings.from_yaml(targets_path.parent, git_dir=git_dir)


def section_files(content_dirs: Iterator[Path]) -> Iterator[Path]:
    for content_dir in content_dirs:
        yield from content_dir.rglob("*.yml")


def content_dirs(git_dir: Path, content_dir: Path) -> Iterator[Path]:
    from itertools import chain

    return chain(
        [content_dir],
        (settings.paths.local_content_dir for settings in all_deck_settings(git_dir)),
    )


def shared_section_ids(content_dir: Path) -> list[str]:
    """List every shared section, as ids usable with `Parser`/`from_section`.

    A directory counts as a section when its own name matches the stem of a \
    `.yml` file directly inside it (e.g. `about/about.yml`).

    Args:
        content_dir: Path to the shared content directory.

    Returns:
        The sorted list of content-relative section ids, e.g. "about" or \
        "python/basics".
    """
    return sorted(
        yml_path.parent.relative_to(content_dir).as_posix()
        for yml_path in content_dir.rglob("*.yml")
        if yml_path.parent.name == yml_path.stem
    )


@contextmanager
def create_pool(processes: int | None = None) -> Iterator[Pool]:
    with get_context("spawn").Pool(processes=processes) as pool:
        yield pool
