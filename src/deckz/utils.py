"""Provide general utility functions that would not fit in other modules."""

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .configuring.paths import Paths
    from .deck_building import Deck


def copy_file_if_newer(original: Path, copy: Path) -> None:
    """Copy `original` to `copy` if `copy` is older than `original` or does not exist.

    Whether `original` is more recent than `copy` or not is determined by the last \
    modification time.

    Args:
        original: Path of the file that you want to copy.
        copy: Path of the destination.
    """
    from shutil import copyfile

    if copy.exists() and copy.stat().st_mtime > original.stat().st_mtime:
        return
    copy.parent.mkdir(parents=True, exist_ok=True)
    copyfile(original, copy)


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


def get_git_dir(path: Path) -> Path:
    """Search and resolve the path of the git dir containing the path given as argument.

    Args:
        path: Path contained in the git dir to search for.

    Raises:
        GitRepositoryNotFoundError: Raised if no git repository is found in the path \
            ancestors.

    Returns:
        Resolved path to the git repository containing the path given as argument.
    """
    from pygit2 import Repository, discover_repository

    from deckz.exceptions import GitRepositoryNotFoundError

    repository = discover_repository(str(path))
    if repository is None:
        msg = "could not find the path of the current git working directory"
        raise GitRepositoryNotFoundError(msg)
    return Path(Repository(repository).workdir).resolve()


def _build_deck(paths: "Paths") -> tuple[Path, "Deck"]:
    from .deck_building import DeckBuilder

    return (
        paths.targets.parent.relative_to(paths.git_dir),
        DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_targets(
            paths.deck_config, paths.targets
        ),
    )


def all_decks(git_dir: Path) -> dict[Path, "Deck"]:
    from multiprocessing import Pool

    with Pool() as pool:
        return dict(pool.map(_build_deck, list(all_paths(git_dir))))


def all_paths(git_dir: Path) -> Iterator["Paths"]:
    """Yield all deck paths that can be found recursively from the git directory.

    Yields:
        Paths of each deck found.
    """
    from .configuring.paths import Paths

    for targets_path in git_dir.rglob("targets.yml"):
        yield Paths(current_dir=targets_path.parent)


def section_files(latex_dirs: Iterator[Path]) -> Iterator[Path]:
    for latex_dir in latex_dirs:
        yield from latex_dir.rglob("*.yml")


def latex_dirs(git_dir: Path, shared_latex_dir: Path) -> Iterator[Path]:
    from itertools import chain

    return chain(
        [shared_latex_dir],
        (paths.local_latex_dir for paths in all_paths(git_dir)),
    )
