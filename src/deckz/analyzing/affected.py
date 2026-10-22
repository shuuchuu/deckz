"""Which decks a change to some files reaches: `deckz show affected`.

A deck is affected by a file it resolves (in French; an English file counts
as its French sibling, which every English build mirrors), or by any file
under its own directory (`deck.yml`, `variables.yml`, its local content).
Which assets a deck shows is only known by rendering its content
(`deck_assets`): `deck_findings` does it, `reaches` and `affected_decks`
don't.
"""

from collections.abc import Callable, Iterable
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..components.checks import Finding
    from ..configuring.settings import DeckSettings


def _french(path: Path) -> Path:
    # `content/x/en/a.md` -> `content/x/a.md`: decks are resolved in French.
    return path.parent.parent / path.name if path.parent.name == "en" else path


def deck_files(settings: "DeckSettings") -> set[Path]:
    """The files the deck of `settings` resolves to, in French.

    Returns:
        Their absolute paths, empty if the deck doesn't parse.
    """
    from ..components.deck_builder import PartDependenciesNodeVisitor
    from ..components.factory import DeckSettingsFactory
    from ..exceptions import DeckzError

    try:
        deck = (
            DeckSettingsFactory(settings, lang="fr")
            .parser()
            .from_deck_definition(settings.paths.deck_definition)
        )
    except DeckzError:
        return set()
    return {
        Path(dependency)
        for part in PartDependenciesNodeVisitor().process(deck).values()
        for dependency in part
    }


def reaches(settings: "DeckSettings") -> Callable[[PurePath], bool]:
    """Whether a change to a path reaches the deck of `settings`.

    Returns:
        The test, taking a path absolute or relative to the repository: \
        under the deck's directory, or a file it resolves (an English file \
        as its French sibling).
    """
    git_dir = settings.paths.git_dir
    deck_dir = settings.paths.current_dir.resolve()
    files = {path.resolve() for path in deck_files(settings)}

    def test(path: PurePath) -> bool:
        target = _french(git_dir / path).resolve()
        return target.is_relative_to(deck_dir) or target in files

    return test


def deck_assets(settings: "DeckSettings") -> set[Path]:
    """The metadata files of the assets the deck of `settings` shows.

    Its content files are rendered, in French and English, as a build
    renders them: an asset counts when a fragment looks up its metadata
    (`<assets_dir>/<asset>.yml`, as `deckz asset search` finds it), whether
    or not the file exists.

    Returns:
        Their resolved paths; a fragment that doesn't render shows none.
    """
    from jinja2 import TemplateError

    from ..components.deck_builder import PartDependenciesNodeVisitor
    from ..components.factory import GlobalSettingsFactory
    from ..exceptions import DeckzError
    from ..models import LANGS
    from ..utils import parse_deck

    renderer = GlobalSettingsFactory(settings).renderer()
    assets_dir = settings.paths.assets_dir
    found: set[Path] = set()
    for lang in LANGS:
        try:
            _, parsed = parse_deck(settings, lang)
        except DeckzError:
            continue  # It doesn't parse: the `deck-definitions` check says why.
        for part in PartDependenciesNodeVisitor().process(parsed.deck).values():
            for dependency in part:
                try:
                    _, usage = renderer.render_to_str(
                        dependency, variables=parsed.variables
                    )
                except (TemplateError, DeckzError, OSError):
                    continue  # `jinja-syntax` reports what doesn't render.
                found |= {(assets_dir / a).with_suffix(".yml").resolve() for a in usage}
    return found


def deck_findings(
    settings: "DeckSettings", findings: Iterable["Finding"]
) -> list["Finding"]:
    """The checks' problems about the deck of `settings`' files.

    A file the deck `reaches`, or an asset it shows (`deck_assets`, an
    asset's file and its metadata file alike: rendered only when some
    problem is about an asset).

    Returns:
        Them, in order. A problem naming no path is about no deck.
    """
    test = reaches(settings)
    assets_dir = settings.paths.assets_dir.resolve()
    git_dir = settings.paths.git_dir
    shown: set[Path] | None = None
    kept = []
    for finding in findings:
        if finding.path is None:
            continue
        if test(finding.path):
            kept.append(finding)
            continue
        path = (git_dir / finding.path).resolve()
        if path.is_relative_to(assets_dir):
            if shown is None:
                shown = deck_assets(settings)
            if path.with_suffix(".yml") in shown:
                kept.append(finding)
    return kept


def affected_decks(git_dir: Path, paths: Iterable[Path]) -> list["DeckSettings"]:
    """Every deck of the repository a change to `paths` reaches.

    Args:
        git_dir: The repository's root.
        paths: Changed files, absolute or relative to `git_dir`.

    Returns:
        The decks' settings, in directory order.
    """
    from ..utils import all_deck_settings

    paths = list(paths)
    if not paths:
        return []
    affected = []
    for settings in all_deck_settings(git_dir):
        test = reaches(settings)
        if any(test(path) for path in paths):
            affected.append(settings)
    return affected


def affected_since(git_dir: Path, since: str) -> list["DeckSettings"]:
    """Every deck the changes since `since` reach, the working tree's included.

    Returns:
        The decks' settings, in directory order.

    Raises:
        DeckzError: If `since` names no commit.
    """
    from ..exceptions import DeckzError
    from ..status import base_revision, changed_paths

    base, _ = base_revision(git_dir, since)
    if base is None:
        msg = f"{since!r} names no commit of {git_dir}"
        raise DeckzError(msg)
    _, changed = changed_paths(git_dir, base)
    return affected_decks(git_dir, [Path(path) for path in changed])
