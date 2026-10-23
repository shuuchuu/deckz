"""Assemble synthetic decks for the `deckz run shared`/`deckz run all` commands.

Both commands validate shared content without needing a full repository \
compile, by building one throwaway [`Deck`][deckz.models.Deck] in memory \
(never written to disk as yaml) containing every shared section expanded \
to a synthetic "all files" flavor -- see \
[`Parser.all_files_section`][deckz.components.parser.Parser.all_files_section].

Each section is its own part, so each compiles to its own PDF: one document \
holding the whole repository's content would need more memory than a \
typical machine has (Typst takes a few MB per page), and a compilation that \
stops at its first error would hide every later section's errors.
"""

from dataclasses import replace
from pathlib import Path, PurePath

from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .configuring.settings import DeckSettings, GlobalSettings
from .models import Deck, Lang, Node, Part, PartName, UnresolvedPath
from .utils import all_deck_settings, shared_section_ids


def _part_name(section_id: str) -> PartName:
    return PartName(section_id.replace("/", "-"))


def check_scratch_dir(git_dir: Path, name: str) -> Path:
    """Directory used as the synthetic `deckz check variables` deck's `current_dir`.

    Created eagerly: `DeckSettings.from_yaml` resolves `git_dir` via \
    `pygit2.discover_repository`, which fails on a path that doesn't exist \
    yet, and the directory is meant to persist across runs anyway (so \
    fragment caching and manual PDF inspection both work).

    Args:
        git_dir: Root of the deckz-managed repository.
        name: Distinguishes the scratch tree from any other under `.check`.

    Returns:
        The (now existing) scratch directory.
    """
    path = git_dir / ".check" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_scratch_dir(git_dir: Path, name: str) -> Path:
    """Directory used as the `deckz run shared`/`deckz run all` deck's `current_dir`.

    Created eagerly: `DeckSettings.from_yaml` resolves `git_dir` via \
    `pygit2.discover_repository`, which fails on a path that doesn't exist \
    yet, and the directory is meant to persist across runs anyway (so \
    fragment caching and manual PDF inspection both work).

    Args:
        git_dir: Root of the deckz-managed repository.
        name: Distinguishes the `run shared`/`run all` scratch trees.

    Returns:
        The (now existing) scratch directory.
    """
    path = git_dir / ".run" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_staged(git_dir: Path) -> Path:
    """Export the git index's staged tree into a persistent scratch directory.

    Used by `deckz check --staged`: it checks the commit, not the working
    tree, since several sessions can share one checkout and an
    in-progress, uncommitted edit must neither block a commit nor let a
    broken one through. The export has no `.git` of its own: a check
    needing one (e.g. a git remote lookup) is expected to fall back to
    doing nothing when it can't find one.

    Args:
        git_dir: Root of the deckz-managed repository.

    Returns:
        The (freshly emptied) scratch directory, holding every tracked \
        file at its staged content.
    """
    from shutil import rmtree
    from subprocess import run

    target = git_dir / ".check" / "staged"
    if target.is_dir():
        rmtree(target)
    target.mkdir(parents=True)
    listing = run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=git_dir,
        capture_output=True,
        check=True,
    ).stdout
    run(
        ["git", "checkout-index", "-z", "--stdin", f"--prefix={target}/"],
        cwd=git_dir,
        input=listing,
        check=True,
    )
    return target


def export_tree(git_dir: Path, commit: str, name: str) -> Path:
    """Export `commit`'s tree into a persistent scratch directory, as `export_staged`.

    Used by `deckz labs publish` to check the notebooks it publishes when
    they're another commit's than the working tree's (the upstream branch's).

    Args:
        git_dir: Root of the deckz-managed repository.
        commit: The commit to export.
        name: The scratch directory's name, under `.check/`.

    Returns:
        The (freshly emptied) scratch directory, holding every file of \
        `commit`.
    """
    from os import environ
    from shutil import rmtree
    from subprocess import run
    from tempfile import TemporaryDirectory

    target = git_dir / ".check" / name
    if target.is_dir():
        rmtree(target)
    target.mkdir(parents=True)
    with TemporaryDirectory() as tmp:
        # A scratch index: the real one stays as the person staged it.
        env = {**environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        run(["git", "read-tree", commit], cwd=git_dir, env=env, check=True)
        run(
            ["git", "checkout-index", "--all", f"--prefix={target}/"],
            cwd=git_dir,
            env=env,
            check=True,
        )
    return target


def content_relative(settings: DeckSettings, path: str) -> str:
    """`path` as `deckz run file`/`section` take it: relative to a content directory.

    A path naming something on disk, from the current directory or the
    repository's root (`content/nn/intro.md`, as editors and `git status` show
    it), under the deck's own content directory or the shared one, is made
    relative to it, without a content file's `.md`. Anything else is kept as
    given: already relative to a content directory (`nn/intro`).

    Returns:
        The path, relative to a content directory.
    """
    paths = settings.paths
    for base in (Path.cwd(), paths.git_dir):
        found = (base / path).resolve()
        if not found.exists():
            continue
        for root in (paths.local_content_dir, paths.content_dir):
            if found.is_relative_to(root.resolve()) and found != root.resolve():
                relative = found.relative_to(root.resolve())
                if found.is_file() and relative.suffix == ".md":
                    relative = relative.with_suffix("")
                return relative.as_posix()
    return path


def chapter_relative(settings: DeckSettings, path: str) -> str | None:
    """The content file whose course notes chapter `path` names, if it names one.

    `path` names a chapter when it's a file of the course notes directory, \
    from the current directory or the repository's root \
    (`course-notes/nn/intro.md`, or its English version \
    `course-notes/nn/en/intro.md`).

    Returns:
        The content file it writes out, as `deckz run file` takes it \
        (`nn/intro`), or None.
    """
    paths = settings.paths
    root = paths.course_notes_dir.resolve()
    for base in (Path.cwd(), paths.git_dir):
        found = (base / path).resolve()
        if not found.is_file() or not found.is_relative_to(root):
            continue
        relative = found.relative_to(root).with_suffix("")
        if relative.parent.name == "en":
            relative = relative.parent.parent / relative.name
        return relative.as_posix()
    return None


def preview_settings(settings: DeckSettings, *parts: str) -> DeckSettings:
    """Copy of a deck's settings writing to a `deckz run file`/`section` scratch tree.

    The deck itself (its `current_dir`, local content dir, variables) stays \
    the same: only the build and output directories move, under \
    `<git_dir>/.run/<parts...>/`, so repeated previews don't clutter the \
    deck's own output.

    Args:
        settings: Settings of the deck the preview is run from.
        parts: Path components of the scratch tree under `.run`, e.g. \
            `("file", "about")`.

    Returns:
        The copy. `settings` is left untouched.
    """
    scratch_dir = settings.paths.git_dir.joinpath(".run", *parts)
    return settings.with_output_dirs(
        scratch_dir / ".build", scratch_dir / "pdf", scratch_dir / "html"
    )


def build_shared_deck(
    settings: GlobalSettings,
    lang: Lang,
    *,
    name: str = "shared",
) -> Deck:
    """Build a deck containing every shared section, expanded to all its files.

    Args:
        settings: Settings of the repository.
        lang: Language to build the deck in.
        name: Name given to the built deck.

    Returns:
        The built deck.
    """
    parser = GlobalSettingsFactory(settings).shared_parser(lang)
    content_dir = settings.paths.content_dir
    deck = Deck(
        name=name,
        parts={
            _part_name(section_id): Part(
                title=None, nodes=(parser.all_files_section(section_id),)
            )
            for section_id in shared_section_ids(content_dir)
        },
    )
    parser.validate(deck)
    return deck


def build_all_deck(settings: GlobalSettings, lang: Lang) -> Deck:
    """Build `build_shared_deck`'s deck, plus every deck-local override.

    For every real deck that locally overrides at least one file of a \
    shared section, adds one extra copy of that section using the deck's \
    own file(s) in place of the shared one(s).

    Args:
        settings: Settings of the repository.
        lang: Language to build the deck in.

    Returns:
        The built deck.
    """
    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    deck = build_shared_deck(settings, lang, name="run-all")
    plain_sections: dict[str, Node] = {
        part.nodes[0].unresolved_path.as_posix(): part.nodes[0]
        for part in deck.parts.values()
    }
    deck_settings = sorted(
        all_deck_settings(git_dir), key=lambda s: s.paths.current_dir.as_posix()
    )
    parts = dict(deck.parts)
    for section_id, plain_section in plain_sections.items():
        if plain_section.parsing_error is not None:
            continue
        counter = 2
        for local_settings in deck_settings:
            parser = DeckSettingsFactory(local_settings, lang=lang).parser()
            candidate = parser.all_files_section(section_id)
            overridden = any(
                node.resolved_path is not None
                and not node.resolved_path.is_relative_to(content_dir)
                for node in candidate.nodes
            )
            if not overridden:
                continue
            label = local_settings.paths.current_dir.relative_to(git_dir).as_posix()
            renamed = replace(
                candidate,
                unresolved_path=UnresolvedPath(PurePath(f"{section_id}-{counter}")),
                title=f"{candidate.title or section_id} [{label}]",
            )
            parts[_part_name(f"{section_id}-{counter}")] = Part(
                title=None, nodes=(renamed,)
            )
            counter += 1
    return replace(deck, parts=parts)
