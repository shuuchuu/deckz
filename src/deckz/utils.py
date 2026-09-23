"""Provide general utility functions that would not fit in other modules."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from multiprocessing import get_context
from multiprocessing.pool import Pool
from pathlib import Path
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import DeckSettings
    from .models import Deck

# Modules loaded by `import_module_from_path`, keyed by what makes a reload
# necessary: a long-lived process (`--watch`) reuses an unchanged module --
# and whatever it memoizes at module level -- across builds, but still picks
# up an edit to it.
_path_modules: dict[tuple[Path, int, str], ModuleType] = {}
_path_modules_lock = Lock()


def copy_file_if_newer(original: Path, copy: Path) -> bool:
    """Copy `original` to `copy` if `copy` is older than `original` or does not exist.

    Whether `original` is more recent than `copy` or not is determined by the last \
    modification time.

    Args:
        original: Path of the file that you want to copy.
        copy: Path of the destination.

    Returns:
        True if the file was copied, False if it wasn't needed.
    """
    from shutil import copyfile

    if copy.exists() and copy.stat().st_mtime > original.stat().st_mtime:
        return False
    copy.parent.mkdir(parents=True, exist_ok=True)
    copyfile(original, copy)
    return True


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
    from yaml import safe_load

    return safe_load(path.read_text(encoding="utf8"))


def load_all_yamls(paths: Iterable[Path]) -> Iterator[Any]:
    for path in paths:
        with suppress(FileNotFoundError):
            yield load_yaml(path)


def _parse_deck(settings: "DeckSettings") -> tuple[Path, "Deck"]:
    from .components.factory import DeckSettingsFactory

    return (
        settings.paths.deck_definition.parent.relative_to(settings.paths.git_dir),
        DeckSettingsFactory(settings)
        .parser()
        .from_deck_definition(settings.paths.deck_definition),
    )


def all_decks(git_dir: Path) -> dict[Path, "Deck"]:
    with create_pool() as pool:
        return dict(pool.map(_parse_deck, list(all_deck_settings(git_dir))))


def all_deck_settings(git_dir: Path) -> Iterator["DeckSettings"]:
    """Yield all deck paths that can be found recursively from the git directory.

    Yields:
        Paths of each deck found.
    """
    from .configuring.settings import DeckSettings

    for targets_path in git_dir.rglob("deck.yml"):
        yield DeckSettings.from_yaml(targets_path.parent)


def section_files(latex_dirs: Iterator[Path]) -> Iterator[Path]:
    for latex_dir in latex_dirs:
        yield from latex_dir.rglob("*.yml")


def latex_dirs(git_dir: Path, latex_dir: Path) -> Iterator[Path]:
    from itertools import chain

    return chain(
        [latex_dir],
        (settings.paths.local_latex_dir for settings in all_deck_settings(git_dir)),
    )


def shared_section_ids(latex_dir: Path) -> list[str]:
    """List every shared section, as ids usable with `Parser`/`from_section`.

    A directory counts as a section when its own name matches the stem of a \
    `.yml` file directly inside it (e.g. `about/about.yml`).

    Args:
        latex_dir: Path to the shared latex directory.

    Returns:
        The sorted list of latex-relative section ids, e.g. "about" or \
        "python/basics".
    """
    return sorted(
        yml_path.parent.relative_to(latex_dir).as_posix()
        for yml_path in latex_dir.rglob("*.yml")
        if yml_path.parent.name == yml_path.stem
    )


@contextmanager
def create_pool(processes: int | None = None) -> Iterator[Pool]:
    with get_context("spawn").Pool(processes=processes) as pool:
        yield pool
