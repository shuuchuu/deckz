"""Analyze fr/en parity of shared sections and decks.

Every function here resolves includes with deckz's own `Parser`/\
`PartDependenciesNodeVisitor`, the same engine used to actually build a deck, so \
results always match what deckz would compile -- as opposed to a naive \
filesystem or grep-based comparison.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath as posix_normpath
from typing import TYPE_CHECKING

from ..models import Deck, FlavorName, ResolvedPath
from ..utils import load_yaml
from .sections_search import flavor_names

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings


@dataclass(frozen=True)
class FilePairing:
    """A resolved fr file and its expected en counterpart."""

    fr_path: Path
    """Resolved absolute path of the fr file."""

    en_path: Path | None
    """Expected absolute path of its en counterpart, None if fr_path does not \
    live under a known latex root (an "unresolvable-root" pairing)."""

    exists_on_disk: bool
    """Whether en_path exists on disk."""

    included: str
    """Whether en_path is actually included by the relevant en deck/section \
    flavor. One of "yes", "no", "no-en-deck", "no-en-yml", "no-such-flavor" or \
    "unresolvable-root"."""


def resolved_files(deck: Deck) -> set[ResolvedPath]:
    """Resolved absolute file paths a deck includes, flattened across parts.

    Returns:
        The set of resolved file paths.
    """
    from ..components.deck_builder import PartDependenciesNodeVisitor

    deps = PartDependenciesNodeVisitor().process(deck)
    paths: set[ResolvedPath] = set()
    for part_paths in deps.values():
        paths.update(part_paths)
    return paths


def en_counterpart(path: Path, fr_root: Path, en_root: Path) -> Path:
    """Compute the expected en counterpart of a resolved fr path.

    Every section directory (shared or local to a deck) that has been \
    translated holds its translated files in a direct "en/" child folder, so \
    the counterpart of `.../<section>/<file>.tex` is `.../<section>/en/<file>\
    .tex`, at any nesting depth.

    Two exceptions to that "sibling en/ folder" rule, both about files that \
    sit directly at a latex root with no enclosing section:

    - a deck-local root file (`fr_root` is `<deck>/latex`, `en_root` is \
        `<deck>/en/latex`) needs no extra "en" segment, since `en_root` is \
        already the en-side latex root;
    - a *shared*-latex root file (`fr_root` and `en_root` are the same \
        `shared/latex` directory) still needs one, under a top-level `en/` \
        folder -- e.g. `shared/latex/contact.tex` counterparts to \
        `shared/latex/en/contact.tex` -- since there is no separate en-side \
        shared latex root to play the role `<deck>/en/latex` plays for a deck.

    This is a heuristic, not a guarantee: an absolute include (rooted at a \
    latex root instead of the current section) can legitimately land on a \
    different file than this rule predicts.

    Returns:
        The expected en counterpart path.
    """
    rel = path.relative_to(fr_root)
    if len(rel.parts) > 1:
        new_rel = rel.parent / "en" / rel.name
    elif fr_root == en_root:
        new_rel = Path("en") / rel.name
    else:
        new_rel = rel
    return en_root / new_rel


def deck_pair(fr_settings: "DeckSettings") -> list[FilePairing]:
    """Pair every file a fr deck resolves to with its expected en counterpart.

    Args:
        fr_settings: Settings of the fr deck to inspect.

    Returns:
        One pairing per file resolved by the deck at `fr_settings`, sorted by \
        fr path.
    """
    from ..components.factory import DeckSettingsFactory
    from ..configuring.settings import DeckSettings

    fr_workdir = fr_settings.paths.current_dir
    fr_deck = (
        DeckSettingsFactory(fr_settings)
        .parser()
        .from_deck_definition(fr_settings.paths.deck_definition)
    )
    fr_shared = fr_settings.paths.shared_latex_dir
    fr_local = fr_settings.paths.local_latex_dir

    en_workdir = fr_workdir / "en"
    en_deck_yml = en_workdir / "deck.yml"
    en_files: set[ResolvedPath] | None = None
    if en_deck_yml.is_file():
        en_settings = DeckSettings.from_yaml(en_workdir)
        en_deck = (
            DeckSettingsFactory(en_settings)
            .parser()
            .from_deck_definition(en_settings.paths.deck_definition)
        )
        en_files = resolved_files(en_deck)

    pairings = []
    for fr_path in sorted(resolved_files(fr_deck)):
        en_path: Path | None
        if fr_path.is_relative_to(fr_shared):
            en_path = en_counterpart(fr_path, fr_shared, fr_shared)
        elif fr_path.is_relative_to(fr_local):
            en_path = en_counterpart(fr_path, fr_local, en_workdir / "latex")
        else:
            en_path = None
        if en_path is None:
            pairings.append(FilePairing(fr_path, None, False, "unresolvable-root"))
            continue
        included = (
            "no-en-deck"
            if en_files is None
            else ("yes" if en_path in en_files else "no")
        )
        pairings.append(FilePairing(fr_path, en_path, en_path.exists(), included))
    return pairings


def _normalized_parts(path_part: str, anchor: str) -> list[str]:
    """Resolve a fr or en include path to a language-agnostic path.

    `anchor` is the section's shared/latex-relative id ("python/basics") for \
    a fr yml, or the same suffixed with "/en" for an en one -- deckz resolves \
    every relative include (no leading "/") against the directory the yml \
    itself lives in, so an en yml routinely needs a leading "../" to reach a \
    sibling of the section root (e.g. fr `oop/oop-python` becomes en `../oop/\
    en/oop-python`). This resolves the path properly with posixpath.normpath \
    before stripping the "en" marker segments, so a fr path and its en \
    counterpart normalize identically regardless of how many directories \
    separate the fr and en ymls.

    Returns:
        The normalized, language-agnostic list of path segments.
    """
    resolved = path_part if path_part.startswith("/") else f"{anchor}/{path_part}"
    return [p for p in posix_normpath(resolved).split("/") if p and p != "en"]


def _normalize_include(item: str | Mapping[str, str], anchor: str) -> str:
    key = item if isinstance(item, str) else next(iter(item))
    if key.startswith("$"):
        path_part, _, flavor_part = key[1:].partition("@")
        parts = _normalized_parts(path_part, anchor)
        name = parts[-1] if parts else path_part
        return f"section:{name}@{flavor_part}"
    return "file:" + "/".join(_normalized_parts(key, anchor))


def _flavors_by_name(yml_path: Path, anchor: str) -> dict[str, Counter[str]]:
    data = load_yaml(yml_path) or {}
    result: dict[str, Counter[str]] = {}
    for flavor in data.get("flavors", []):
        name = flavor["name"]
        result[name] = Counter(
            _normalize_include(item, anchor) for item in flavor.get("includes", [])
        )
    return result


def section_flavor_diff(shared_latex_dir: Path, section: str) -> list[str]:
    """Structurally compare a shared section's fr flavors against its en/en.yml.

    This does NOT use deckz's resolver -- it's a direct, cheap comparison of \
    each flavor's normalized "includes" list. It cannot catch an absolute \
    include that silently resolves to the wrong (fr) file while still \
    normalizing to a matching key on both sides -- see `section_en_leak` for \
    that.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        section: Shared/latex-relative section id, e.g. "python/basics".

    Returns:
        One finding per line, empty if the section is fr/en-clean:
            `NO_FR_YML <path>` -- section has no fr yml (bug)
            `NO_EN_YML <path>` -- section has no en/en.yml at all
            `MISSING_FLAVOR <name>` -- flavor only in fr
            `EXTRA_FLAVOR <name>` -- flavor only in en
            `FLAVOR <name> MISSING <key> x<count>` -- entry only in fr's flavor
            `FLAVOR <name> EXTRA <key> x<count>` -- entry only in en's flavor
    """
    section_dir = shared_latex_dir / section
    fr_yml = section_dir / f"{section_dir.name}.yml"
    en_yml = section_dir / "en" / "en.yml"
    findings: list[str] = []
    if not fr_yml.is_file():
        findings.append(f"NO_FR_YML {fr_yml}")
        return findings
    fr_flavors = _flavors_by_name(fr_yml, section)
    if not en_yml.is_file():
        findings.append(f"NO_EN_YML {en_yml}")
        findings.extend(f"MISSING_FLAVOR {name}" for name in fr_flavors)
        return findings
    en_flavors = _flavors_by_name(en_yml, f"{section}/en")

    fr_names, en_names = set(fr_flavors), set(en_flavors)
    for name in sorted(fr_names - en_names):
        findings.append(f"MISSING_FLAVOR {name}")
    for name in sorted(en_names - fr_names):
        findings.append(f"EXTRA_FLAVOR {name}")
    for name in sorted(fr_names & en_names):
        fr_c, en_c = fr_flavors[name], en_flavors[name]
        for key, count in (fr_c - en_c).items():
            findings.append(f"FLAVOR {name} MISSING {key} x{count}")
        for key, count in (en_c - fr_c).items():
            findings.append(f"FLAVOR {name} EXTRA {key} x{count}")
    return findings


def _section_flavor_deck(
    shared_latex_dir: Path, file_extension: str, section: str, flavor: FlavorName
) -> Deck:
    from ..components.parser import Parser

    parser = Parser(
        local_latex_dir=shared_latex_dir,
        shared_latex_dir=shared_latex_dir,
        file_extension=file_extension,
    )
    return parser.from_section(section, flavor)


def section_files(
    shared_latex_dir: Path, file_extension: str, section: str, flavor: FlavorName
) -> set[ResolvedPath]:
    """Resolved absolute file paths a shared section+flavor includes.

    Recurses into subsections, exactly like deckz would when building a deck \
    that includes `$<section>@<flavor>`.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        file_extension: Extension to consider when resolving files.
        section: Shared/latex-relative section id, e.g. "python/basics".
        flavor: Flavor to resolve.

    Returns:
        The set of resolved file paths.
    """
    return resolved_files(
        _section_flavor_deck(shared_latex_dir, file_extension, section, flavor)
    )


def section_pair(
    shared_latex_dir: Path, file_extension: str, section: str, flavor: FlavorName
) -> list[FilePairing]:
    """Pair a shared section+flavor's resolved files with their en counterpart.

    The section-level equivalent of `deck_pair`.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        file_extension: Extension to consider when resolving files.
        section: Shared/latex-relative section id, e.g. "python/basics".
        flavor: Flavor to resolve.

    Returns:
        One pairing per file resolved by `section`@`flavor`, sorted by fr path. \
        `included` is one of "yes", "no", "no-en-yml" (no en/en.yml at all) or \
        "no-such-flavor" (en/en.yml exists but has no such flavor, or it fails \
        to resolve, e.g. a referenced subsection has no en/ yet).
    """
    section_dir = shared_latex_dir / section
    en_yml = section_dir / "en" / "en.yml"
    fr_deck = _section_flavor_deck(shared_latex_dir, file_extension, section, flavor)

    en_available = en_yml.is_file()
    en_files: set[ResolvedPath] | None = None
    if en_available:
        try:
            en_deck = _section_flavor_deck(
                shared_latex_dir, file_extension, f"{section}/en", flavor
            )
        except Exception:
            en_files = None
        else:
            en_files = resolved_files(en_deck)

    pairings = []
    for fr_path in sorted(resolved_files(fr_deck)):
        en_path = en_counterpart(fr_path, shared_latex_dir, shared_latex_dir)
        if not en_available:
            included = "no-en-yml"
        elif en_files is None:
            included = "no-such-flavor"
        else:
            included = "yes" if en_path in en_files else "no"
        pairings.append(FilePairing(fr_path, en_path, en_path.exists(), included))
    return pairings


def section_en_leak(
    shared_latex_dir: Path, file_extension: str, section: str
) -> list[str]:
    """Flag any file an en section flavor resolves to that isn't itself under en/.

    Complementary to `section_flavor_diff`: resolves every flavor declared in \
    `<section>/en/en.yml` with deckz's own engine and flags any resolved `.tex` \
    file that does not sit under an "en" path segment -- no exceptions. This \
    catches drift `section_flavor_diff` is structurally blind to: an absolute \
    include that forgot its "/en" suffix (e.g. "$/python/databases@light" \
    instead of "$/python/databases/en@light") normalizes to the same key on \
    both sides, so the structural diff sees a match while deckz silently \
    resolves to the French shared file.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        file_extension: Extension to consider when resolving files.
        section: Shared/latex-relative section id, e.g. "python/basics".

    Returns:
        One finding per line, empty if clean:
            `NO_EN_YML <path>` -- nothing to check yet
            `FLAVOR <name> LEAK <path>` -- resolved file outside any en/ dir
            `FLAVOR <name> ERROR <message>` -- flavor failed to resolve (e.g. a \
                referenced subsection has no en/ yet -- a prerequisite, not a \
                leak)
    """
    section_dir = shared_latex_dir / section
    en_yml = section_dir / "en" / "en.yml"
    if not en_yml.is_file():
        return [f"NO_EN_YML {en_yml}"]

    findings: list[str] = []
    for name in sorted(flavor_names(en_yml)):
        try:
            deck = _section_flavor_deck(
                shared_latex_dir, file_extension, f"{section}/en", name
            )
            paths = resolved_files(deck)
        except Exception as exc:
            findings.append(f"FLAVOR {name} ERROR {exc}")
            continue
        for path in sorted(paths):
            if "en" not in path.parts:
                findings.append(f"FLAVOR {name} LEAK {path}")
    return findings
