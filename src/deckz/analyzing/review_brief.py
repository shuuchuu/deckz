"""What a reviewer of a shared section needs first, in one call: `deckz review brief`.

A section's review starts by assembling its scope from several commands:
the files decks include under it with their frames and review states
(`review status`), the flavors and the decks using them (`deps`, `show
affected`), its lab notebooks, the findings its reports keep open or
refused (`review findings`), whether its dated facts are due
(`review-dated-facts`), and what changed since its last review in what
decides its audiences (its flavors' definitions, its decks' own files).
`section_brief` gathers them, parsing the decks once.

The *units* are its reports: each file goes to the report whose mark it
has, else to the innermost section report (under `review.dir`'s
`sections/`) that exists for its directory or a parent's, since a report
covers the subsections that have none of their own, else to the section's
own report, to be written. Its lab notebooks are those under the notebooks
directory at the section's path (a lab belongs to the section of its path,
`labs.ids.lab_section`), and the files other than content files its
units' reports record.
"""

import subprocess
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..exceptions import ReviewError

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings
    from ..models import Node, ParsedDeck, Section
    from .dated_facts import DatedFacts
    from .findings import Finding
    from .review import FileReview, Report


@dataclass(frozen=True)
class BriefFile:
    review: "FileReview"
    flavors: tuple[str, ...]
    """The section's flavors including it, in the section's order."""
    decks: int
    """How many decks include it."""


@dataclass(frozen=True)
class BriefLab:
    lab: str
    """Its directory, relative to the repository."""
    files: tuple["FileReview", ...]
    """Its notebooks."""


@dataclass(frozen=True)
class BriefUnit:
    report: str
    """Relative to the repository."""
    exists: bool
    date: date | None
    """Of its last mark; None if it has none."""
    base: str | None
    files: tuple[BriefFile, ...]
    """Its content files, by path."""
    labs: tuple[BriefLab, ...]
    others: tuple["FileReview", ...]
    """The other files it records, neither content files nor notebooks."""
    findings: tuple["Finding", ...]
    """Every finding of the report, in its order."""
    dated_facts: "DatedFacts | None"
    """None unless `review.dated_facts` is set and the report exists."""
    changed: tuple[str, ...] | None
    """Since `base`, the files deciding its audiences that changed: the \
    section's definitions (`.yml`) and its decks' own files, `en/` left out; \
    None without a base in this clone."""


@dataclass(frozen=True)
class BriefFlavor:
    name: str
    files: int
    frames: int
    decks: tuple[str, ...]
    """The decks including it, sorted."""


@dataclass(frozen=True)
class BriefDeck:
    deck: str
    """Its directory, relative to the repository."""
    uses: tuple[str, ...]
    """How it includes the section: `<section>@<flavor>` for a flavor of it \
    or of a subsection, a path under the shared content directory for a file \
    included alone; the outermost ones, in the deck's order."""
    frames: int
    """The frames of the section's files it includes."""
    total: int
    """All its frames."""


@dataclass(frozen=True)
class SectionBrief:
    section: str
    """Relative to the shared content directory."""
    units: tuple[BriefUnit, ...]
    """By report."""
    flavors: tuple[BriefFlavor, ...]
    """In the section's definition's order."""
    decks: tuple[BriefDeck, ...]
    """By directory."""
    problems: tuple[str, ...]
    """The reports that couldn't be read, and the findings breaking the grammar."""


def brief_section(settings: "GlobalSettings", given: Path) -> str:
    """The shared section a path given to `deckz review brief` names.

    Args:
        settings: The repository's settings.
        given: As given: a section's directory (from the current directory \
            or the repository's root), its path under the shared content \
            directory, or its report under `review.dir`'s `sections/`.

    Returns:
        The section, relative to the shared content directory.

    Raises:
        ReviewError: If it names none.
    """
    from .review import SECTIONS_DIR, locate, review_dir

    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    sections = review_dir(settings) / SECTIONS_DIR
    candidates = [] if given.is_absolute() else [content_dir / given]
    with suppress(ReviewError):  # Outside the repository: not a path then.
        candidates.insert(0, locate(settings, given))
    for candidate in candidates:
        found = candidate
        if found.suffix == ".md" and found.is_relative_to(sections):
            found = content_dir / found.relative_to(sections).with_suffix("")
        if (
            found.is_dir()
            and found.is_relative_to(content_dir)
            and found != content_dir
        ):
            return found.relative_to(content_dir).as_posix()
    msg = (
        f"{given} names no shared section: give its directory (e.g. "
        f"{content_dir.relative_to(git_dir).as_posix()}/<section>), its path "
        f"under it, or its report under {sections.relative_to(git_dir).as_posix()}"
    )
    raise ReviewError(msg)


def _uses(nodes: Iterable["Node"], section: PurePosixPath, target: Path) -> list[str]:
    # The outermost includes of `section` or a subsection among `nodes`, and
    # the files under its directory `target` included alone.
    from ..models import Section

    found: list[str] = []
    for node in nodes:
        if isinstance(node, Section):
            path = PurePosixPath(node.unresolved_path.as_posix())
            if path == section or path.is_relative_to(section):
                found.append(f"{path}@{node.flavor}")
            else:
                found.extend(_uses(node.nodes, section, target))
        elif node.resolved_path is not None:
            resolved = Path(node.resolved_path)
            if resolved.is_relative_to(target):
                found.append((section / resolved.relative_to(target)).as_posix())
    return found


def _report_for(
    settings: "GlobalSettings", directory: str, section: str, existing: set[str]
) -> str:
    # The innermost existing section report for `directory` (relative to the
    # shared content directory), else the section's own.
    from .review import SECTIONS_DIR, review_dir

    reports = (review_dir(settings) / SECTIONS_DIR).relative_to(settings.paths.git_dir)
    path = PurePosixPath(directory)
    for candidate in (path, *path.parents):
        if candidate.as_posix() == ".":
            break
        if (rel := (reports / f"{candidate}.md").as_posix()) in existing:
            return rel
    return (reports / f"{section}.md").as_posix()


def _changed_since(
    git_dir: Path, base: str, target: str, section: str, decks: Sequence[str]
) -> tuple[str, ...] | None:
    # Since `base` (working tree included), the tracked files deciding the
    # audiences that changed: the section's definitions (under `target`,
    # relative to the repository), the decks' own files but their local
    # content other than the section's, `en/` left out; None if this clone
    # lacks `base`.
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(git_dir), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    if git("cat-file", "-e", f"{base}^{{commit}}").returncode:
        return None
    out = git("diff", "--name-only", base, "--", f"{target}/*.yml", *decks).stdout
    local = PurePosixPath("content") / section
    found = []
    for line in out.splitlines():
        path = PurePosixPath(line)
        if not line or "en" in path.parts:
            continue
        deck = next((d for d in decks if path.is_relative_to(d)), None)
        if deck is not None:
            own = path.relative_to(deck)
            if own.parts[0] == "content" and not own.is_relative_to(local):
                continue
        found.append(line)
    return tuple(sorted(found))


def _flavor_files(
    settings: "GlobalSettings",
    section: str,
    target: Path,
    decks: Mapping[Path, "ParsedDeck"],
) -> dict[str, list[str]]:
    # Each flavor of the section's own definition, with its files (relative
    # to the repository, in include order): as the shared content resolves
    # them, else, for a flavor including a deck's own file, as the first
    # deck including it does (none if no deck does).
    from ..exceptions import DeckzError
    from ..models import SectionDefinition
    from ..utils import load_yaml
    from .sections_analyzer import ordered_files
    from .sections_search import ordered_section_files

    definition = target / f"{target.name}.yml"
    if not definition.is_file():
        return {}
    git_dir = settings.paths.git_dir
    found: dict[str, list[str]] = {}
    for flavor in SectionDefinition.model_validate(load_yaml(definition)).flavors:
        try:
            paths = [
                Path(p) for p in ordered_section_files(settings, section, flavor.name)
            ]
        except DeckzError:
            node = _section_node(decks, section, flavor.name)
            paths = [] if node is None else [Path(p) for p in ordered_files(node.nodes)]
        found[flavor.name] = [p.relative_to(git_dir).as_posix() for p in paths]
    return found


def _section_node(
    decks: Mapping[Path, "ParsedDeck"], section: str, flavor: str
) -> "Section | None":
    # The first include of `section@flavor` in the decks.
    from ..models import Section

    def search(nodes: Iterable["Node"]) -> Section | None:
        for node in nodes:
            if isinstance(node, Section):
                if node.unresolved_path.as_posix() == section and node.flavor == flavor:
                    return node
                if (found := search(node.nodes)) is not None:
                    return found
        return None

    for _, parsed in sorted(decks.items()):
        for part in parsed.deck.parts.values():
            if (found := search(part.nodes)) is not None:
                return found
    return None


def section_brief(
    settings: "GlobalSettings",
    section: str,
    decks: Mapping[Path, "ParsedDeck"] | None = None,
) -> SectionBrief:
    """`deckz review brief`: what a reviewer of `section` reads first.

    Args:
        settings: The repository's settings.
        section: Relative to the shared content directory (`brief_section`).
        decks: Every deck parsed in French (`utils.all_decks`), when already \
            parsed.

    Returns:
        Its brief. Fails (`review_dir`) if `review.dir` is unset.
    """
    from ..utils import all_decks
    from .findings import deck_dirs, parse, scope_problems
    from .review import (
        all_reports,
        marks_index,
        report_paths,
        review_dir,
        review_files,
        used_files,
        used_under,
    )

    review_dir(settings)
    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    target = content_dir / section
    frames: dict[Path, int] = {}
    if decks is None:
        decks = all_decks(git_dir, "fr")
    reports, problems = all_reports(settings)
    by_report = {report.path: report for report in reports}
    existing = {p.relative_to(git_dir).as_posix() for p in report_paths(settings)}
    index = marks_index(git_dir, reports)
    used = used_files(settings, decks)
    content = used_under(settings, target, used)
    flavor_files = _flavor_files(settings, section, target, decks)
    members = {name: set(files) for name, files in flavor_files.items()}

    files: dict[str, list[BriefFile]] = {}
    for review in review_files(settings, content, index):
        report = review.report or _report_for(
            settings,
            (git_dir / review.path).parent.relative_to(content_dir).as_posix(),
            section,
            existing,
        )
        flavors = tuple(name for name, paths in members.items() if review.path in paths)
        files.setdefault(report, []).append(
            BriefFile(review, flavors, len(used[review.path]))
        )
    extras = _extras(settings, section, content, [by_report.get(r) for r in files])
    labs: dict[str, dict[str, list[FileReview]]] = {}
    others: dict[str, list[FileReview]] = {}
    notebooks_dir = settings.paths.labs_notebooks_dir
    for review in review_files(settings, extras, index):
        absolute = git_dir / review.path
        lab = absolute.parent
        report = review.report or _report_for(
            settings,
            _lab_section(settings, lab) if absolute.suffix == ".ipynb" else section,
            section,
            existing,
        )
        if absolute.suffix == ".ipynb" and absolute.is_relative_to(notebooks_dir):
            rel = lab.relative_to(git_dir).as_posix()
            labs.setdefault(report, {}).setdefault(rel, []).append(review)
        else:
            others.setdefault(report, []).append(review)

    grammar = settings.review.findings
    every_deck = deck_dirs(git_dir)
    facts = _dated_facts(settings, [git_dir / r for r in (*files, *labs, *others)])
    uses = _deck_uses(section, target, decks, frames)
    deck_paths = [deck.deck for deck in uses]
    section_rel = target.relative_to(git_dir).as_posix()
    units = []
    for report in sorted({*files, *labs, *others}):
        found = by_report.get(report)
        findings: tuple[Finding, ...] = ()
        if grammar is not None and (git_dir / report).is_file():
            read = parse((git_dir / report).read_text(encoding="utf8"), grammar, report)
            findings = read.findings
            problems.extend(read.problems)
            problems.extend(scope_problems(settings, read, every_deck))
        base = found.base if found is not None else None
        units.append(
            BriefUnit(
                report,
                report in existing,
                found.date if found is not None else None,
                base,
                tuple(files.get(report, ())),
                tuple(
                    BriefLab(lab, tuple(reviews))
                    for lab, reviews in sorted(labs.get(report, {}).items())
                ),
                tuple(others.get(report, ())),
                findings,
                facts.get(report),
                None
                if base is None
                else _changed_since(git_dir, base, section_rel, section, deck_paths),
            )
        )
    flavors = tuple(
        BriefFlavor(
            name,
            len(paths),
            sum(_frames(git_dir / path, frames) for path in paths),
            tuple(d.deck for d in uses if f"{section}@{name}" in d.uses),
        )
        for name, paths in flavor_files.items()
    )
    return SectionBrief(section, tuple(units), flavors, tuple(uses), tuple(problems))


def _lab_section(settings: "GlobalSettings", lab: Path) -> str:
    from ..labs.ids import lab_section

    notebooks_dir = settings.paths.labs_notebooks_dir
    if not lab.is_relative_to(notebooks_dir):
        return "."
    return lab_section(lab.relative_to(notebooks_dir), settings.paths.content_dir)


def _extras(
    settings: "GlobalSettings",
    section: str,
    content: Sequence[str],
    reports: Iterable["Report | None"],
) -> list[str]:
    # The section's notebooks, and the other files its reports record that
    # aren't content files.
    from .review import is_content_path

    git_dir = settings.paths.git_dir
    root = settings.paths.labs_notebooks_dir / section
    found: dict[str, None] = dict.fromkeys(
        p.relative_to(git_dir).as_posix()
        for p in sorted(root.rglob("*.ipynb") if root.is_dir() else ())
    )
    skipped = set(content)
    for report in reports:
        if report is None:
            continue
        found.update(
            dict.fromkeys(
                path
                for path in report.files
                if path not in skipped and not is_content_path(settings, git_dir / path)
            )
        )
    return sorted(found)


def _dated_facts(
    settings: "GlobalSettings", reports: Sequence[Path]
) -> dict[str, "DatedFacts"]:
    from .dated_facts import dated_facts

    existing = [path for path in reports if path.is_file()]
    if not existing:
        return {}
    return {facts.report: facts for facts in dated_facts(settings, existing)}


def _frames(path: Path, cache: dict[Path, int]) -> int:
    # A content file's frames, each file read once.
    from .sections_analyzer import frame_count

    if path not in cache:
        cache[path] = frame_count(path) if path.is_file() else 0
    return cache[path]


def _deck_uses(
    section: str,
    target: Path,
    decks: Mapping[Path, "ParsedDeck"],
    frames: dict[Path, int],
) -> list[BriefDeck]:
    # Every deck including a file under the section, with how it does.
    from .sections_analyzer import ordered_files

    pure = PurePosixPath(section)
    found = []
    for deck_path, parsed in sorted(decks.items()):
        nodes = [node for part in parsed.deck.parts.values() for node in part.nodes]
        uses = list(dict.fromkeys(_uses(nodes, pure, target)))
        paths = [Path(p) for p in ordered_files(nodes)]
        inside = [p for p in paths if p.is_relative_to(target)]
        if not uses and not inside:
            continue
        found.append(
            BriefDeck(
                deck_path.as_posix(),
                tuple(uses),
                sum(_frames(p, frames) for p in inside),
                sum(_frames(p, frames) for p in paths),
            )
        )
    return found
