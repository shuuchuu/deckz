"""Provide general utility functions that would not fit in other modules."""

from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from logging import getLogger
from multiprocessing import get_context
from multiprocessing.pool import Pool
from pathlib import Path, PurePath, PurePosixPath
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any

from .run_cache import in_shared_run, run_resource, shared

if TYPE_CHECKING:
    from .configuring.settings import DeckSettings
    from .exceptions import DeckzError
    from .models import Lang, Node, ParsedDeck

# Modules loaded by `import_module_from_path`, keyed by what makes a reload
# necessary: a long-lived process (`--watch`) reuses an unchanged module --
# and whatever it memoizes at module level -- across builds, but still picks
# up an edit to it.
_path_modules: dict[tuple[Path, int, str], ModuleType] = {}
_path_modules_lock = Lock()
_logger = getLogger(__name__)


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
    _replace_atomically(copy, lambda temporary: copyfile(original, temporary))
    return True


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` in one step, as seen from other processes.

    A process reading `path` meanwhile (a deck compiling while assets build) \
    sees its old content or its new one, never a truncated file, and a write \
    failing midway leaves the old content whole.
    """
    _replace_atomically(path, lambda temporary: temporary.write_bytes(data))


def _replace_atomically(path: Path, write: Callable[[Path], object]) -> None:
    """Have `write` fill a temporary file next to `path`, then move it there."""
    import os
    from threading import get_ident

    temporary = path.with_name(f".{path.name}.{os.getpid()}-{get_ident()}.tmp")
    try:
        write(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path, waiting_message: str) -> Generator[None]:
    """Hold an exclusive `flock` on `path`, across deckz processes.

    The kernel releases it when its process exits, however it exits. Each \
    call opens the file anew, so two holders in one process contend like \
    two processes would.

    Args:
        path: The lock file, created (with its directory) if missing.
        waiting_message: Logged when another holder makes this one wait.

    Yields:
        Once the lock is held, until exiting.
    """
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _logger.info(waiting_message)
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


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

    From https://github.com/allenai/allennlp/blob/master/allennlp/common/util.py,
    listing each level with `iter_modules`, which imports nothing: `walk_packages`
    would import a subpackage under its bare name (a `matplotlib/` or `collections/`
    subpackage would import the real library and walk it).

    Args:
        package_name: Name of the package to fully import.
    """
    from importlib import import_module, reload
    from importlib import invalidate_caches as importlib_invalidate_caches
    from pkgutil import iter_modules
    from sys import modules

    importlib_invalidate_caches()

    if package_name in modules:
        module = modules[package_name]
        reload(module)
    else:
        module = import_module(package_name)
    for _, name, _ in iter_modules(getattr(module, "__path__", [])):
        import_module_and_submodules(f"{package_name}.{name}")


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


def yaml_safe_loader() -> type:
    """PyYAML's safe loader, libyaml's when PyYAML has it.

    libyaml's is 8 to 10 times faster than the pure Python one, for the same
    data: a deck loads each section it includes, again for every deck (1,200
    loads for 43 decks), and `review-headers` reads every report's header.

    Returns:
        The loader class, for `yaml.load(text, Loader=...)`.
    """
    import yaml

    return getattr(yaml, "CSafeLoader", yaml.SafeLoader)


# What `load_yaml` read, by path, with the stat that dates it: every deck loads
# the repository's `deckz.yml` (a thousand lines) and the user's, and a deck
# parse each section it includes, again for every deck. The stat keeps a long
# process (`--watch`) reading an edited file anew; one entry per path keeps it
# from growing with each edit.
_yaml_cache: dict[Path, tuple[tuple[int, int, int], Any]] = {}


def load_yaml(path: Path) -> Any:
    """Load a YAML file, from a cache while it's unchanged.

    Returns:
        Its data, a copy of its own the caller may change.

    Raises:
        InvalidConfigurationError: If it isn't valid YAML.
    """
    from copy import deepcopy

    from yaml import YAMLError, load

    from .exceptions import InvalidConfigurationError

    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    cached = _yaml_cache.get(path)
    if cached is not None and cached[0] == stamp:
        return deepcopy(cached[1])
    try:
        data = load(path.read_text(encoding="utf8"), Loader=yaml_safe_loader())
    except (YAMLError, UnicodeDecodeError) as e:
        msg = f"{path} is not valid YAML:\n{e}"
        raise InvalidConfigurationError(msg) from e
    _yaml_cache[path] = (stamp, data)
    return deepcopy(data)


def load_all_yamls(paths: Iterable[Path]) -> Iterator[Any]:
    for path in paths:
        with suppress(FileNotFoundError):
            yield load_yaml(path)


def deck_name_from_dir(current_dir: Path) -> str:
    """The lowercased `name` a deck directory's own `deck.yml` declares.

    A `deckz run file`/`deckz run section` preview has no `deck.yml` of its \
    own (it's compiled as a synthetic deck, see `Parser.from_file`/ \
    `from_section`): its directory gets the same fallback name they use.

    Returns:
        `deck.yml`'s `name`, lowercased, or `"deck"` if there's no `deck.yml`.
    """
    config = current_dir / "deck.yml"
    if not config.is_file():
        return "deck"
    return str(load_yaml(config)["name"]).lower()


def parse_deck(settings: "DeckSettings", lang: "Lang") -> tuple[Path, "ParsedDeck"]:
    """Parse a deck with its variables as in a build, as `all_decks` does.

    In English, a file with no `en/` version is left out (see `all_decks`).

    Returns:
        The deck's directory relative to the repository, and the parsed deck.

    Raises:
        DeckParsingError: If the deck doesn't parse in French.
    """
    from .components.factory import DeckSettingsFactory
    from .configuring.variables import get_variables
    from .exceptions import DeckParsingError
    from .models import ParsedDeck

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
        ParsedDeck(deck, {**variables, "lang": lang}),
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


def all_decks(git_dir: Path, lang: "Lang" = "fr") -> dict[Path, "ParsedDeck"]:
    """Parse every deck of the repository, with its variables as in a build.

    Args:
        git_dir: Root of the repository.
        lang: Language to resolve the decks in. Under "en", files resolve \
            exactly as with `--lang en`, except a file with no `en/` counterpart \
            is left out of the tree instead of failing the parse, so \
            analyses see every translation that does exist.

    Returns:
        The parsed decks, keyed by their directory relative to `git_dir`.
    """
    return all_decks_by_lang(git_dir, (lang,))[lang]


def all_decks_by_lang(
    git_dir: Path, langs: Iterable["Lang"]
) -> dict["Lang", dict[Path, "ParsedDeck"]]:
    """Parse every deck of the repository in each of `langs`, as `all_decks` does.

    One pool parses them all: each pool started spawns its processes and
    imports deckz in them again, which costs about as much as the parsing.
    In a `shared_run`, each language is parsed once for the whole run, in
    the run's pool (`deck_results`). The first deck that doesn't parse (in
    French), or whose variables don't load, raises its error.

    Returns:
        For each language, the parsed decks keyed by their directory \
        relative to `git_dir`.
    """
    langs = tuple(dict.fromkeys(langs))
    if in_shared_run():
        results = {lang: deck_results(git_dir, lang) for lang in langs}
    else:
        settings = list(all_deck_settings(git_dir))
        with create_pool() as pool:
            results = _parsed_by_lang(settings, langs, pool)
    found: dict[Lang, dict[Path, ParsedDeck]] = {}
    for lang, parsed in results.items():
        found[lang] = {}
        for _, result in parsed:
            if isinstance(result, BaseException):
                raise result
            path, deck = result
            found[lang][path] = deck
    return found


type DeckResult = tuple[Path, ParsedDeck] | DeckzError
"""A deck parsed (its directory relative to the repository, and the deck), \
or why it didn't parse."""


@shared
def deck_results(
    git_dir: Path, lang: "Lang"
) -> tuple[tuple["DeckSettings", DeckResult], ...]:
    """Every deck parsed in `lang` as `parse_deck` does, or the error it raised.

    A deck that doesn't parse leaves the others parsed: `deck-definitions`
    reports it, and an analysis that needs every deck raises it
    (`all_decks_by_lang`). Shared in a run (`run_cache`), in the run's pool.

    Returns:
        Each deck's settings and result, in `all_deck_settings`' order.
    """
    settings = list(all_deck_settings(git_dir))
    if not settings:
        return ()
    if in_shared_run():
        pool = run_resource("deckz.utils.create_pool", create_pool)
        return _parsed_by_lang(settings, (lang,), pool)[lang]
    with create_pool() as pool:
        return _parsed_by_lang(settings, (lang,), pool)[lang]


def _parsed_by_lang(
    settings: list["DeckSettings"], langs: tuple["Lang", ...], pool: Pool
) -> dict["Lang", tuple[tuple["DeckSettings", DeckResult], ...]]:
    jobs = [(deck, lang) for lang in langs for deck in settings]
    parsed = pool.starmap(_parse_deck_or_error, jobs) if jobs else []
    found: dict[Lang, list[tuple[DeckSettings, DeckResult]]] = {
        lang: [] for lang in langs
    }
    for (deck, lang), result in zip(jobs, parsed, strict=True):
        found[lang].append((deck, result))
    return {lang: tuple(results) for lang, results in found.items()}


def _parse_deck_or_error(settings: "DeckSettings", lang: "Lang") -> DeckResult:
    # In a pool's worker: an error comes back as a result, so one deck that
    # doesn't parse doesn't lose the others' (`DeckParsingError` pickles).
    from .exceptions import DeckzError

    try:
        return parse_deck(settings, lang)
    except DeckzError as error:
        return error


def all_deck_settings(git_dir: Path) -> Iterator["DeckSettings"]:
    """Yield the settings of every deck found recursively under the git directory.

    Each deck's own settings are loaded (a deck directory may have its own \
    `deckz.yml`), but the repository root is `git_dir`, not rediscovered.
    Found once per run (`run_cache`).

    Yields:
        Settings of each deck found.
    """
    yield from _all_deck_settings(git_dir)


@shared
def _all_deck_settings(git_dir: Path) -> tuple["DeckSettings", ...]:
    from os import walk

    from .configuring.settings import DeckSettings

    found = []
    for root, dirs, files in walk(git_dir):
        # Skip hidden directories, pruned before descending into them: build
        # directories (`.build`, `.run`) can hold a deck.yml (e.g. a symlink to
        # their deck's) and aren't decks, and `.git`/`.venv` are large.
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "deck.yml" in files:
            found.append(DeckSettings.from_yaml(Path(root), git_dir=git_dir))
    return tuple(found)


@shared
def repo_files(git_dir: Path) -> tuple[str, ...]:
    """Every file of `git_dir` git would commit, relative to it.

    In a checkout: the tracked files that exist and the untracked ones
    `.gitignore` doesn't exclude (builds are). In `deckz check --staged`'s
    export, which has no `.git`: all of them. Listed once per run
    (`run_cache`), for the checks of a repository's `templates/checks.py`.

    Returns:
        The paths, POSIX-style, sorted.
    """
    import subprocess

    if not (git_dir / ".git").exists():
        return tuple(
            sorted(
                path.relative_to(git_dir).as_posix()
                for path in git_dir.rglob("*")
                if not path.is_dir()
            )
        )
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=git_dir,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    # --cached also lists the tracked files deleted from the checkout.
    return tuple(
        sorted(
            path
            for path in dict.fromkeys(listing.split("\0"))
            if path and (git_dir / path).exists()
        )
    )


def section_files(content_dirs: Iterator[Path]) -> Iterator[Path]:
    for content_dir in content_dirs:
        yield from content_dir.rglob("*.yml")


def content_dirs(git_dir: Path, content_dir: Path) -> Iterator[Path]:
    from itertools import chain

    return chain(
        [content_dir],
        (settings.paths.local_content_dir for settings in all_deck_settings(git_dir)),
    )


# Notes for the coding agents working in their directory (e.g. a `content/CLAUDE.md`
# telling them how sections are written), never content, wherever they are.
AGENT_NOTES = frozenset({"AGENTS.md", "CLAUDE.md"})


def is_content_file(path: PurePath, file_extensions: Iterable[str]) -> bool:
    """Whether `path` names a content file, by its name only.

    Returns:
        True if it has one of `file_extensions` and isn't agent notes.
    """
    return path.suffix in file_extensions and path.name not in AGENT_NOTES


def content_files(directory: Path, file_extensions: Iterable[str]) -> Iterator[Path]:
    """Every content file under `directory`, recursively.

    Yields:
        Each file, by extension in the order of `file_extensions`, then sorted.
    """
    for extension in file_extensions:
        for path in sorted(directory.rglob(f"*{extension}")):
            if path.name not in AGENT_NOTES:
                yield path


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
def create_pool(processes: int | None = None) -> Generator[Pool]:
    with get_context("spawn").Pool(processes=processes) as pool:
        yield pool
