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
    end: int = 0
    """Its last line in the report (from 1), the blank lines after it left out."""
    text: str = ""
    """Its lines as written, list marker included, from `line` to `end`."""


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
    lines = text.splitlines()
    for item in _items(text, settings.heading):
        match = _ID.match(item.lines[0])
        assert match is not None  # `_items` keeps those only.
        letters, number = match.group(1), int(match.group(2))
        numbers[letters] = max(numbers.get(letters, 0), number)
        found = pattern.findall("\n".join(item.lines))
        written = lines[item.line - 1 : item.line - 1 + len(item.lines)]
        while written and not written[-1].strip():
            written.pop()
        finding = Finding(
            id=f"{letters}{number}",
            rubric=letters,
            number=number,
            line=item.line,
            outcome=outcome_of[found[-1]] if found else None,
            heading=item.heading,
            summary=_summary(item),
            scope=_scope(item, match.end()),
            end=item.line - 1 + len(written),
            text="\n".join(written),
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


def fiche(text: str, heading: str) -> str:
    """A report's fiche: its body before its findings, the part read in their stead.

    Args:
        text: The report.
        heading: The findings heading's text (`review.findings.heading`).

    Returns:
        The lines after the front matter and before the first heading whose \
        text is `heading` (outside code blocks), with a final newline; the \
        whole body if it has no such heading.
    """
    lines = text.splitlines()
    start = _body_start(lines)
    end = len(lines)
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is not None:
            stripped = line.strip()
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                fence = None
        elif opening := _FENCE.match(line):
            fence = opening.group(1)
        elif (match := _HEADING.match(line)) and (
            match.group(2) or ""
        ).strip() == heading:
            end = index
            break
    body = "\n".join(lines[start:end]).strip("\n")
    return f"{body}\n" if body else ""


_TITLE = 72
"""The longest title a compacted finding keeps, in characters."""
_MENTION = 40
"""The longest mention of how it was done a compacted finding keeps."""
_MARKS = 3
"""The most commits and days a compacted finding keeps."""
_MARK = re.compile(
    r"(?<![0-9A-Za-z])(?:\d{4}-\d{2}-\d{2}"
    r"|(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40})(?![0-9A-Za-z])"
)
"""A day (`2026-11-04`) or a commit (`66fa0179`, at least a digit and a letter)."""
_CODE_SPAN = re.compile(r"`[^`]*`")


def _shortened(text: str, limit: int) -> str:
    # `text` cut at a word to fit `limit` with its ellipsis, no code span or
    # emphasis left open.
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    while cut.count("`") % 2:
        cut = cut[: cut.rfind("`")]
    # An emphasis left open, outside the code spans.
    while (outside := _CODE_SPAN.sub(lambda m: " " * len(m[0]), cut)).count("*") % 2:
        cut = cut[: outside.rfind("*")]
    return cut.rstrip(" ,;:([«\N{EM DASH}\N{EN DASH}-") + "\N{HORIZONTAL ELLIPSIS}"


def _parenthesized(text: str) -> str | None:
    # What the parentheses `text` starts with hold (to its end if unclosed).
    if not text.startswith("("):
        return None
    depth = 0
    for index, char in enumerate(text):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            return text[1:index]
    return text[1:]


def _marks(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in _MARK.finditer(text)))


def _done_with(finding: Finding, outcomes: re.Pattern[str]) -> str:
    # How a done finding was done, in parentheses: the commits and days that
    # follow its outcome word, else what follows it, shortened, else the
    # last commits and days it cites.
    matches = list(outcomes.finditer(finding.text))
    after = finding.text[matches[-1].end() :].lstrip() if matches else ""
    mention = _parenthesized(after)
    if mention is not None:
        if marks := _marks(mention):
            return f" ({', '.join(marks[:_MARKS])})"
        if collapsed := " ".join(mention.split()):
            return f" ({_shortened(collapsed, _MENTION)})"
    marks = _marks(finding.text)[-_MARKS:]
    return f" ({', '.join(marks)})" if marks else ""


def _title(finding: Finding, outcomes: re.Pattern[str]) -> str:
    # Its first paragraph up to a sub-list or an outcome word, shortened;
    # what follows when that leaves nothing (an id alone, then a sub-list).
    lines = finding.text.splitlines()
    marker = _ITEM.match(lines[0])
    head = [lines[0][marker.end() :] if marker else lines[0]]
    rest = []
    for index, line in enumerate(lines[1:], 1):
        if not line.strip() or _starts_block(line.lstrip(" ")):
            rest = lines[index:]
            break
        head.append(line)
    text = " ".join(" ".join(head).split())
    text = _ID.sub("", text, count=1)
    if scope := _SCOPE.match(text):
        text = text[scope.end() :]
    text = text.strip().lstrip("\N{EM DASH}\N{EN DASH}-: ")
    if match := outcomes.search(text):
        text = text[: match.start()]
    text = text.strip().rstrip(" ,;:.")
    if not text:
        text = " ".join(" ".join(rest).split())
        match = outcomes.search(text)
        text = (text[: match.start()] if match else text).strip()
    return _shortened(text, _TITLE)


def compact(
    text: str, settings: "FindingsSettings", report: str = "<report>"
) -> tuple[str, tuple[str, ...]]:
    """Reduce each done finding of a report to one line; git keeps its text.

    The line is the finding's list marker, its id, its scope, a short title
    (its first paragraph, up to `_TITLE` characters), its outcome word and,
    in parentheses, the commits and days its outcome cites (else what it
    says, shortened): `- **I1** — `a.md`, « Types » : `int`… *done*
    (66fa0179)`. Open and refused findings, and the rest of the report, stay
    as they are. A finding stays too when its line wouldn't be shorter, so a
    report compacted once is left unchanged.

    Args:
        text: The report.
        settings: The grammar (`review.findings`).
        report: Its path relative to the repository, for the problems.

    Returns:
        The compacted report, and the ids of the findings compacted, in \
        the report's order.

    Raises:
        ReviewError: If the compacted report doesn't read as the same \
            findings, which would be a bug: nothing is written then.
    """
    found = parse(text, settings, report)
    outcomes = _outcome_pattern(settings)
    done = settings.outcomes.done
    lines = text.splitlines(keepends=True)
    compacted: list[str] = []
    for finding in reversed(found.findings):
        if finding.outcome != "done":
            continue
        first = lines[finding.line - 1]
        marker = _ITEM.match(first)
        assert marker is not None  # A finding starts a list item.
        scope = f" [{', '.join(finding.scope)}]" if finding.scope else ""
        ending = lines[finding.end - 1][len(lines[finding.end - 1].rstrip("\r\n")) :]
        line = (
            f"{first[: marker.end()]}**{finding.id}**{scope} \N{EM DASH} "
            f"{_title(finding, outcomes)} *{done}*{_done_with(finding, outcomes)}"
            f"{ending}"
        )
        before = "".join(lines[finding.line - 1 : finding.end])
        if len(line.encode("utf8")) < len(before.encode("utf8")):
            lines[finding.line - 1 : finding.end] = [line]
            compacted.append(finding.id)
    result = "".join(lines)
    again = parse(result, settings, report)

    def read(
        found: ReportFindings,
    ) -> list[tuple[str, Outcome | None, tuple[str, ...]]]:
        return [(f.id, f.outcome, f.scope) for f in found.findings]

    if read(again) != read(found) or len(again.problems) != len(found.problems):
        msg = (
            f"{report}: compacting would change its findings, a bug of deckz: "
            "nothing written, report it with the report attached"
        )
        raise ReviewError(msg)
    return result, tuple(reversed(compacted))


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


########################################################################################
# Fiches and compaction                                                                #
########################################################################################


def section_report(settings: "GlobalSettings", given: Path) -> Path:
    """The report a section or a report given on the command line stands for.

    Args:
        settings: The repository's settings.
        given: As given: a report (a Markdown file under `review.dir`), or \
            a shared section, by its directory (from the current directory \
            or the repository's root) or its path under the shared content \
            directory.

    Returns:
        The report, absolute: a section's is `<review.dir>/sections/<its \
        path under the shared content directory>.md`.

    Raises:
        ReviewError: If `given` names neither, or its report doesn't exist.
    """
    from contextlib import suppress

    from .review import SECTIONS_DIR, locate, review_dir

    git_dir = settings.paths.git_dir
    directory = review_dir(settings)
    content_dir = settings.paths.content_dir
    candidates = [] if given.is_absolute() else [content_dir / given]
    with suppress(ReviewError):  # Outside the repository: not a path then.
        candidates.insert(0, locate(settings, given))
    report = None
    for candidate in candidates:
        if candidate.suffix == ".md" and candidate.is_relative_to(directory):
            report = candidate
        elif candidate.is_dir() and candidate.is_relative_to(content_dir):
            section = candidate.relative_to(content_dir).as_posix()
            report = directory / SECTIONS_DIR / f"{section}.md"
        if report is not None:
            break
    else:
        msg = (
            f"{given} is neither a report (a Markdown file under "
            f"{directory.relative_to(git_dir).as_posix()}) nor a shared section "
            f"(e.g. {content_dir.relative_to(git_dir).as_posix()}/<section>, or "
            "<section>)"
        )
        raise ReviewError(msg)
    if not report.is_file():
        msg = (
            f"no report {report.relative_to(git_dir).as_posix()}: a review writes "
            "it, `deckz review mark` records its files"
        )
        raise ReviewError(msg)
    return report


def report_fiche(settings: "GlobalSettings", target: Path) -> tuple[str, str]:
    """`deckz review fiche`: a report's fiche (`fiche`).

    Args:
        settings: The repository's settings.
        target: A report, or a shared section, as given (`section_report`).

    Returns:
        The report, relative to the repository, and its fiche. Fails if \
        `review.findings` is unset.
    """
    report = section_report(settings, target)
    text = report.read_text(encoding="utf8")
    rel = report.relative_to(settings.paths.git_dir).as_posix()
    return rel, fiche(text, grammar(settings).heading)


@dataclass(frozen=True)
class Compaction:
    report: str
    """Relative to the repository."""
    ids: tuple[str, ...]
    """The findings reduced to one line, in the report's order."""
    before: int
    """The report's size before, in bytes."""
    after: int
    """Its size after."""


def compact_reports(
    settings: "GlobalSettings", targets: Sequence[Path], *, dry_run: bool = False
) -> list[Compaction]:
    """`deckz review compact`: reduce the reports' done findings to one line each.

    Args:
        settings: The repository's settings.
        targets: Reports, or directories under `review.dir` standing for the \
            reports under them, absolute (`review.locate`).
        dry_run: Only say what would be reduced, write nothing.

    Returns:
        One per report, by path, even those with nothing to reduce.

    Raises:
        ReviewError: If a target is no report, or `review.dir` or \
            `review.findings` is unset.
    """
    from .review import report_paths, review_dir

    directory = review_dir(settings)
    found_grammar = grammar(settings)
    git_dir = settings.paths.git_dir
    paths: dict[Path, None] = {}
    every = report_paths(settings)
    for target in targets:
        if target.is_dir() and target.is_relative_to(directory):
            paths.update(dict.fromkeys(p for p in every if p.is_relative_to(target)))
        elif target.suffix == ".md" and target.is_relative_to(directory):
            if not target.is_file():
                msg = f"no report {target.relative_to(git_dir).as_posix()}"
                raise ReviewError(msg)
            paths[target] = None
        else:
            msg = (
                f"{target.relative_to(git_dir).as_posix() or '.'} is not a report: "
                "give reports (Markdown files under "
                f"{directory.relative_to(git_dir).as_posix()}, `review.dir`) or "
                "directories holding them"
            )
            raise ReviewError(msg)
    done = []
    for path in sorted(paths):
        rel = path.relative_to(git_dir).as_posix()
        # Bytes, so that its line endings stay as they are.
        text = path.read_bytes().decode("utf8")
        result, ids = compact(text, found_grammar, rel)
        if ids and not dry_run:
            path.write_bytes(result.encode("utf8"))
        done.append(
            Compaction(rel, ids, len(text.encode("utf8")), len(result.encode("utf8")))
        )
    return done
