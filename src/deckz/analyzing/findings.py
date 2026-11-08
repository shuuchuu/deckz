"""The findings of the review reports: `deckz review findings`, `review-findings`.

The reports under `review.dir` (`deckz.analyzing.review`) are the
repository's own text, except for one grammar `deckz.yml` sets
(`review.findings`), so that deckz can count what's left to do:

```yaml
review:
  findings:
    heading: Constats
    rubrics: {E: Erreurs, I: Incohérences, P: Faiblesses pédagogiques}
    outcomes: {open: ouvert, done: fait, refused: refusé}
```

The findings are under the heading whose text is `heading`, at any level,
up to the next heading of that level or above. The headings one level
below it are the rubrics (deeper ones only divide a rubric). A *finding* is
a top-level list item there whose text starts with its id in bold: a
rubric's letters and a number (`- **P3** — …`). The item runs as Markdown
says: its indented lines, the blank lines between them, and the lines
continuing its last paragraph without indentation. Its *outcome* is the
last outcome word in it, emphasized (`*ouvert*`), wherever it is: after a
sub-list, or followed by the commit or the reason in parentheses. Other
list items (a verdict, a list of what was checked) are not findings.

A finding of a shared section's report concerns, by default, every deck
that report covers. One that concerns only some of them names them, its
*scope*, in brackets right after its id: `- **A3** [orsys/mle, orsys/iao] —
…`. An entry is a deck's directory relative to the repository, or its end
(`orsys/mle` for `decks/orsys/mle`) when one deck only ends so. Then
`deckz review findings <deck>` and the dashboard count it for those decks
only, and for them even when their files aren't in its report (a notion a
deck needs from a section it doesn't include). A deck's own report needs
no scope: its findings are its deck's.

The `review-findings` check fails on a finding with no outcome, an id two
findings share in a report, letters no rubric has, a finding under the
heading of another rubric, or of none, a scope in a deck's report, and an
open finding whose scope entry names no deck, or several.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..exceptions import ReviewError

if TYPE_CHECKING:
    from ..configuring.settings import FindingsSettings, GlobalSettings

Outcome = Literal["open", "done", "refused"]
OUTCOMES: tuple[Outcome, ...] = ("open", "done", "refused")

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_ITEM = re.compile(r"^( {0,3}(?:[-*+]|\d{1,9}[.)]))( +|$)")
_FENCE = re.compile(r"^ *(`{3,}|~{3,})")
_BREAK = re.compile(r"^ {0,3}([-*_])(?: *\1){2,} *$")
_ID = re.compile(r"\*\*([A-Z]+)(\d+)\*\*")
_SCOPE = re.compile(r"[ \t]*\[([^\]\n]*)\]")


@dataclass(frozen=True)
class Finding:
    id: str
    """Its rubric's letters and its number, e.g. `P3`."""
    rubric: str
    """The letters, e.g. `P`."""
    number: int
    line: int
    """Its first line in the report (from 1)."""
    outcome: Outcome | None
    """None when it has none (the check fails)."""
    heading: str | None
    """The rubric heading it's under, None if it's under none."""
    summary: str
    """Its first paragraph after the id (and its scope), whitespace collapsed."""
    scope: tuple[str, ...] = ()
    """The decks it concerns, as written in brackets after its id; empty: \
    every deck its report covers (`resolve_scope`)."""


@dataclass(frozen=True)
class ReportFindings:
    report: str
    """Relative to the repository."""
    findings: tuple[Finding, ...]
    """In the report's order."""
    problems: tuple[str, ...] = ()
    """What breaks the grammar, one line each, `<report>:<line>: …`."""

    def count(self, outcome: Outcome | None, rubric: str | None = None) -> int:
        """How many of its findings have `outcome` (and are of `rubric`).

        Returns:
            The count.
        """
        return sum(
            f.outcome == outcome and (rubric is None or f.rubric == rubric)
            for f in self.findings
        )


@dataclass(frozen=True)
class TargetFindings:
    target: str
    """As given, relative to the repository."""
    kind: Literal["deck", "paths"]
    reports: tuple[ReportFindings, ...]
    """A deck's: its own report and those recording one of its content files \
    or written French chapters (`review.deck_covered_paths`), reduced to the \
    findings concerning it, and the other reports' findings naming it \
    (`deck_findings`); else the reports under the path, or recording a file \
    under it."""


@dataclass(frozen=True)
class FindingsStatus:
    reports: tuple[ReportFindings, ...]
    """With no target, every report."""
    targets: tuple[TargetFindings, ...]
    problems: tuple[str, ...]
    """The reports that couldn't be read, and the findings that break the \
    grammar."""


########################################################################################
# Parsing                                                                              #
########################################################################################


def grammar(settings: "GlobalSettings") -> "FindingsSettings":
    """The findings grammar of the repository.

    Returns:
        `review.findings`.

    Raises:
        ReviewError: If it isn't set.
    """
    if settings.review.findings is None:
        msg = (
            "no findings grammar: set `review.findings` in deckz.yml, e.g. "
            "`findings: {heading: Findings, rubrics: {E: Errors, I: "
            "Inconsistencies}, outcomes: {open: open, done: done, refused: "
            "refused}}` under `review`"
        )
        raise ReviewError(msg)
    return settings.review.findings


@dataclass
class _Item:
    line: int
    indent: int
    """Where its content starts: a line indented this much continues it."""
    lines: list[str]
    heading: str | None
    finding: bool
    """Under the findings heading, starting with an id."""


def _body_start(lines: Sequence[str]) -> int:
    # The index of the first line after the front matter.
    if not lines or lines[0].rstrip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return index + 1
    return 0


def _starts_block(line: str) -> bool:
    # Whether `line`, unindented, starts a block rather than continuing a
    # paragraph.
    stripped = line.lstrip(" ")
    return bool(
        _HEADING.match(line)
        or _ITEM.match(line)
        or _FENCE.match(line)
        or _BREAK.match(line)
        or stripped.startswith((">", "|", "<"))
    )


class _Scanner:
    """The top-level list items under the findings headings, line by line."""

    def __init__(self, heading: str) -> None:
        self.heading = heading
        self.items: list[_Item] = []
        self.current: _Item | None = None
        self.fence: str | None = None
        """The open code fence's backticks or tildes."""
        self.level: int | None = None
        """The findings heading's level, while under it."""
        self.rubric: str | None = None

    def scan(self, index: int, line: str) -> None:
        if self.fence is not None:
            if self.current is not None:
                self.current.lines.append(line)
            stripped = line.strip()
            if stripped.startswith(self.fence) and not stripped.strip(self.fence[0]):
                self.fence = None
        elif not self._continues(line):
            self.current = None
            self._top_level(index, line)

    def _continues(self, line: str) -> bool:
        # Whether `line` belongs to the current item: blank, indented as its
        # content, or continuing its paragraph without indentation.
        current = self.current
        if current is None:
            return False
        blank = not line.strip()
        indent = len(line) - len(line.lstrip(" "))
        lazy = not blank and current.lines[-1].strip() and not _starts_block(line)
        if not (blank or indent >= current.indent or lazy):
            return False
        current.lines.append(line)
        if opening := _FENCE.match(line):
            self.fence = opening.group(1)
        return True

    def _top_level(self, index: int, line: str) -> None:
        if opening := _FENCE.match(line):
            self.fence = opening.group(1)
        elif match := _HEADING.match(line):
            self._heading(len(match.group(1)), (match.group(2) or "").strip())
        elif match := _ITEM.match(line):
            content = line[match.end() :]
            self.current = _Item(
                line=index + 1,
                indent=match.end(),
                lines=[content],
                heading=self.rubric,
                finding=self.level is not None and _ID.match(content) is not None,
            )
            self.items.append(self.current)

    def _heading(self, depth: int, title: str) -> None:
        if title == self.heading:
            self.level, self.rubric = depth, None
        elif self.level is not None and depth <= self.level:
            self.level = self.rubric = None
        elif self.level is not None and depth == self.level + 1:
            self.rubric = title


def _items(text: str, heading: str) -> list[_Item]:
    # The findings' items, with the rubric heading each is under.
    lines = text.splitlines()
    scanner = _Scanner(heading)
    for index in range(_body_start(lines), len(lines)):
        scanner.scan(index, lines[index])
    return [item for item in scanner.items if item.finding]


def _outcome_pattern(settings: "FindingsSettings") -> re.Pattern[str]:
    words = "|".join(
        re.escape(getattr(settings.outcomes, outcome)) for outcome in OUTCOMES
    )
    return re.compile(rf"(?<![*\w])\*({words})\*(?![*\w])")


def _summary(item: _Item) -> str:
    first: list[str] = []
    for line in item.lines:
        if not line.strip():
            break
        first.append(line.strip())
    text = " ".join(first)
    text = _ID.sub("", text, count=1)
    if scope := _SCOPE.match(text):
        text = text[scope.end() :]
    return text.strip().lstrip("\N{EM DASH}\N{EN DASH}-: ").strip()


def _scope(item: _Item, id_end: int) -> tuple[str, ...]:
    match = _SCOPE.match(item.lines[0], id_end)
    if match is None:
        return ()
    return tuple(e.strip() for e in match.group(1).split(",") if e.strip())


def parse(
    text: str, settings: "FindingsSettings", report: str = "<report>"
) -> ReportFindings:
    """Read a report's findings.

    Args:
        text: The report.
        settings: The grammar (`review.findings`).
        report: Its path relative to the repository, for the problems.

    Returns:
        Its findings and what breaks the grammar.
    """
    outcome_of = {getattr(settings.outcomes, o): o for o in OUTCOMES}
    pattern = _outcome_pattern(settings)
    by_heading = {title: letters for letters, title in settings.rubrics.items()}
    letters_list = ", ".join(f"{k} ({v})" for k, v in settings.rubrics.items())
    words = ", ".join(f"*{getattr(settings.outcomes, o)}*" for o in OUTCOMES)
    findings: list[Finding] = []
    problems: list[str] = []
    first_line: dict[str, int] = {}
    numbers: dict[str, int] = {}
    for item in _items(text, settings.heading):
        match = _ID.match(item.lines[0])
        assert match is not None  # `_items` keeps those only.
        letters, number = match.group(1), int(match.group(2))
        numbers[letters] = max(numbers.get(letters, 0), number)
        found = pattern.findall("\n".join(item.lines))
        finding = Finding(
            id=f"{letters}{number}",
            rubric=letters,
            number=number,
            line=item.line,
            outcome=outcome_of[found[-1]] if found else None,
            heading=item.heading,
            summary=_summary(item),
            scope=_scope(item, match.end()),
        )
        findings.append(finding)
        where = f"{report}:{item.line}: {finding.id}"
        if finding.outcome is None:
            problems.append(
                f"{where} has no outcome: write one of {words} in it, its last "
                "such word being the outcome"
            )
        if letters not in settings.rubrics:
            problems.append(
                f"{where}: no rubric has the letters {letters} (deckz.yml's "
                f"`review.findings.rubrics`: {letters_list}): give it one's "
                "letters, or add the rubric"
            )
        elif by_heading.get(item.heading or "") != letters:
            if item.heading is None:
                under = "under no rubric heading"
            elif item.heading in by_heading:
                under = f"under « {item.heading} », rubric {by_heading[item.heading]}"
            else:
                under = f"under « {item.heading} », which is no rubric"
            problems.append(
                f"{where} is {under}: move it under « {settings.rubrics[letters]} »"
            )
        if finding.id in first_line:
            problems.append(
                f"{where} is also the id of line {first_line[finding.id]}: give "
                "the newer one the next free number of its rubric "
                "(ids are never renumbered)"
            )
        else:
            first_line[finding.id] = item.line
    return ReportFindings(report, tuple(findings), tuple(problems))


########################################################################################
# Reports                                                                              #
########################################################################################


def read_findings(settings: "GlobalSettings", path: Path) -> ReportFindings:
    """Read the findings of one report.

    Args:
        settings: The repository's settings.
        path: The report, absolute.

    Returns:
        Its findings. Fails (`grammar`) if `review.findings` is unset.
    """
    rel = path.relative_to(settings.paths.git_dir).as_posix()
    return parse(path.read_text(encoding="utf8"), grammar(settings), rel)


########################################################################################
# Scopes                                                                               #
########################################################################################


def deck_dirs(git_dir: Path) -> tuple[str, ...]:
    """Every deck's directory, relative to the repository, as scopes name them.

    Returns:
        The directories holding a `deck.yml` (hidden ones skipped, as
        `utils.all_deck_settings` does), sorted.
    """
    from os import walk

    found = []
    for root, dirs, files in walk(git_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "deck.yml" in files:
            found.append(Path(root).relative_to(git_dir).as_posix())
    return tuple(sorted(found))


def resolve_scope(entry: str, decks: Sequence[str]) -> tuple[str, ...]:
    """The decks a scope entry names.

    Args:
        entry: As written (`orsys/mle`, or `decks/orsys/mle`).
        decks: Every deck's directory (`deck_dirs`).

    Returns:
        The deck whose directory is `entry`, else those whose directory ends
        with it: one when the entry is good, none or several otherwise.
    """
    entry = entry.strip("/")
    if entry in decks:
        return (entry,)
    return tuple(d for d in decks if d.endswith(f"/{entry}"))


def concerns(finding: Finding, deck: str, decks: Sequence[str]) -> bool:
    """Whether a scoped finding names a deck (an unscoped one names none).

    Returns:
        True if one of its scope's entries resolves to `deck` alone.
    """
    return any(resolve_scope(e, decks) == (deck,) for e in finding.scope)


def scope_problems(
    settings: "GlobalSettings", found: ReportFindings, decks: Sequence[str]
) -> list[str]:
    """What's wrong with a report's scopes.

    A deck's report has none (its findings are its deck's), and an open
    finding's entries each name one deck. A closed one may name a deck since
    removed (a past INTRA session's): it's history.

    Returns:
        The problems, one line each.
    """
    from .review import report_kind

    kind = report_kind(settings, settings.paths.git_dir / found.report)
    is_deck = kind is not None and kind[0] == "deck"
    problems = []
    for finding in found.findings:
        where = f"{found.report}:{finding.line}: {finding.id}"
        if finding.scope and is_deck:
            problems.append(
                f"{where} has a scope, in a deck's report: its findings are its "
                "deck's, remove the brackets"
            )
            continue
        if finding.outcome != "open":
            continue
        for entry in finding.scope:
            named = resolve_scope(entry, decks)
            if not named:
                problems.append(
                    f"{where}: its scope's « {entry} » names no deck: write a "
                    "deck's directory (or its end), or remove it from the scope"
                )
            elif len(named) > 1:
                problems.append(
                    f"{where}: its scope's « {entry} » names several decks "
                    f"({', '.join(named)}): write the one's directory"
                )
    return problems


def deck_findings(
    deck: str,
    own: str,
    covering: Iterable[str],
    every: Mapping[str, ReportFindings],
    decks: Sequence[str],
) -> list[ReportFindings]:
    """A deck's findings: those of its report, and those that concern it.

    Args:
        deck: The deck's directory, relative to the repository.
        own: Its report, relative to the repository.
        covering: The reports recording one of its files.
        every: Every report's findings, by report.
        decks: Every deck's directory (`deck_dirs`).

    Returns:
        Its own report whole; each covering report reduced to its unscoped
        findings and those naming the deck (kept even if that leaves none);
        and any other report reduced to its findings naming the deck, when
        it has some. By report.
    """
    covered = set(covering)
    shown = []
    for report, found in sorted(every.items()):
        if report == own:
            shown.append(found)
            continue
        kept = tuple(
            f
            for f in found.findings
            if (report in covered and not f.scope) or concerns(f, deck, decks)
        )
        if report in covered or kept:
            shown.append(ReportFindings(report, kept))
    return shown


def findings_problems(
    settings: "GlobalSettings", paths: Iterable[Path] | None
) -> list[str]:
    """The `review-findings` check: every finding follows the grammar.

    Args:
        settings: The repository's settings.
        paths: Only check the reports among these (absolute paths); None for \
            every report.

    Returns:
        The problems, one line each; none when `review.dir` or \
        `review.findings` is unset.
    """
    from .review import reports_among

    if settings.review.dir is None or settings.review.findings is None:
        return []
    decks = deck_dirs(settings.paths.git_dir)
    problems = []
    for path in reports_among(settings, paths):
        found = read_findings(settings, path)
        problems.extend(found.problems)
        problems.extend(scope_problems(settings, found, decks))
    return problems


def _covering(
    settings: "GlobalSettings", target: Path, recorded: Mapping[str, frozenset[str]]
) -> tuple[Literal["deck", "paths"], list[str]]:
    # The kind of `target` and the reports it stands for.
    from ..configuring.settings import DeckSettings
    from .review import deck_covered_paths, deck_report_path, review_dir

    git_dir = settings.paths.git_dir
    if (target / "deck.yml").is_file():
        deck = DeckSettings.from_yaml(target, git_dir=git_dir)
        files = deck_covered_paths(deck)
        own = deck_report_path(settings, target.relative_to(git_dir).as_posix())
        own_rel = own.relative_to(git_dir).as_posix()
        return "deck", [
            r for r, paths in recorded.items() if paths & files or r == own_rel
        ]
    rel = target.relative_to(git_dir).as_posix()
    if target.is_relative_to(review_dir(settings)):
        return "paths", [
            r for r in recorded if r == rel or r.startswith(f"{rel}/") or not rel
        ]
    return "paths", [
        r
        for r, paths in recorded.items()
        if not rel or any(p == rel or p.startswith(f"{rel}/") for p in paths)
    ]


def findings_status(
    settings: "GlobalSettings", targets: Sequence[Path]
) -> FindingsStatus:
    """`deckz review findings`: the findings of every report, or the targets'.

    Args:
        settings: The repository's settings.
        targets: Decks' directories or paths, absolute (`review.locate`); \
            none for every report.

    Returns:
        The findings. Fails if `review.dir` or `review.findings` is unset.
    """
    from .review import deck_report_path, read_report, report_paths, review_dir

    review_dir(settings)
    grammar(settings)
    git_dir = settings.paths.git_dir
    decks = deck_dirs(git_dir)
    every: dict[str, ReportFindings] = {}
    recorded: dict[str, frozenset[str]] = {}
    problems: list[str] = []
    for path in report_paths(settings):
        found = read_findings(settings, path)
        every[found.report] = found
        problems.extend(found.problems)
        problems.extend(scope_problems(settings, found, decks))
        try:
            recorded[found.report] = frozenset(read_report(settings, path).files)
        except ReviewError as error:
            recorded[found.report] = frozenset()
            problems.append(str(error))
    if not targets:
        return FindingsStatus(tuple(every.values()), (), tuple(problems))
    shown = []
    for target in targets:
        kind, reports = _covering(settings, target, recorded)
        rel = target.relative_to(git_dir).as_posix()
        if kind == "deck":
            own = deck_report_path(settings, rel).relative_to(git_dir).as_posix()
            found_reports = deck_findings(rel, own, reports, every, decks)
        else:
            found_reports = [every[report] for report in sorted(reports)]
        shown.append(TargetFindings(rel or ".", kind, tuple(found_reports)))
    return FindingsStatus((), tuple(shown), tuple(problems))
