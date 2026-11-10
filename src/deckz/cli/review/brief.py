from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from datetime import date

    from ...analyzing.review_brief import BriefUnit, SectionBrief

_OUTCOMES = ("open", "done", "refused")


@app.command()
def brief(
    section: Path,
    /,
    *,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Print what a review of a shared section starts from, in one call.

    The files decks include under SECTION, each with its review state (as
    `deckz review status` gives it: a stale file's lines added and removed,
    and the frames they touch), its frames, how many decks include it and
    which of the section's flavors do, grouped by report: the one whose
    mark a file has, else the innermost section report there is for its
    directory or a parent's, else the section's own, to be written. Under
    each report, its lab notebooks (those under the notebooks directory at
    the section's path, and the other files it records), its open and
    refused findings one line each, when its dated facts are due, and what
    changed since its last mark among the section's definitions (`.yml`)
    and its decks' own files. Then the section's flavors, with their frames
    and the decks including them, and every deck including one of its
    files, with how (`<section>@<flavor>`, or a file alone) and the
    section's frames out of its own.

    Always exits 0: it only informs.

    Args:
        section: A shared section: its directory (`content/python/basics`),
            its path under the shared content directory (`python/basics`),
            or its report under `review.dir`'s `sections/`
        json: Print one JSON object instead: `{section, units: [{report,
            exists, date, base, files, labs: [{lab, files}], others,
            counts: {open, done, refused}, findings, dated_facts: {checked,
            source, months, due_on, due} or null, changed}], flavors: [{name,
            files, frames, decks}], decks: [{deck, uses, frames, total}],
            problems}`; a file is as in `deckz review status --json`, a
            content file with its `flavors` and `decks` (a count) too, a
            finding (open or refused only) as in `deckz review findings
            --json`, and `changed` null when the report's base isn't in this
            clone
        workdir: Path to move into before running the command

    """
    from datetime import date
    from sys import stderr

    from ...analyzing.review_brief import brief_section, section_brief
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = section_brief(settings, brief_section(settings, section))
    today = date.today()
    if json:
        from .._presentation import print_json

        print_json(_json(found, today))
        return
    git_dir = settings.paths.git_dir
    content = (settings.paths.content_dir / found.section).relative_to(git_dir)
    labs = (settings.paths.labs_notebooks_dir / found.section).relative_to(git_dir)
    _print(found, content.as_posix(), labs.as_posix(), today)
    for problem in found.problems:
        print(f"problem: {problem}", file=stderr)


def _json(found: "SectionBrief", today: "date") -> dict[str, object]:
    from .findings import _finding_json
    from .status import _file_json

    def unit(u: "BriefUnit") -> dict[str, object]:
        facts = u.dated_facts
        return {
            "report": u.report,
            "exists": u.exists,
            "date": None if u.date is None else u.date.isoformat(),
            "base": u.base,
            "files": [
                {**_file_json(f.review), "flavors": list(f.flavors), "decks": f.decks}
                for f in u.files
            ],
            "labs": [
                {"lab": lab.lab, "files": [_file_json(r) for r in lab.files]}
                for lab in u.labs
            ],
            "others": [_file_json(r) for r in u.others],
            "counts": {o: sum(f.outcome == o for f in u.findings) for o in _OUTCOMES},
            "findings": [
                _finding_json(f) for f in u.findings if f.outcome in ("open", "refused")
            ],
            "dated_facts": None
            if facts is None
            else {
                "checked": None if facts.checked is None else facts.checked.isoformat(),
                "source": facts.source,
                "months": facts.months,
                "due_on": None if facts.due_on is None else facts.due_on.isoformat(),
                "due": facts.due(today),
            },
            "changed": None if u.changed is None else list(u.changed),
        }

    return {
        "section": found.section,
        "units": [unit(u) for u in found.units],
        "flavors": [
            {
                "name": f.name,
                "files": f.files,
                "frames": f.frames,
                "decks": list(f.decks),
            }
            for f in found.flavors
        ],
        "decks": [
            {"deck": d.deck, "uses": list(d.uses), "frames": d.frames, "total": d.total}
            for d in found.decks
        ],
        "problems": list(found.problems),
    }


def _under(path: str, root: str) -> str:
    # `path` from `root` when under it, else whole.
    return path[len(root) + 1 :] if path.startswith(f"{root}/") else path


def _print(found: "SectionBrief", content: str, labs: str, today: "date") -> None:
    files = [f for u in found.units for f in u.files]
    frames = sum(f.review.frames or 0 for f in files)
    print(
        f"{content}: {len(files)} files decks include, {frames} frames; "
        f"{len(found.flavors)} flavors, {len(found.decks)} decks; "
        f"{len(found.units)} reports"
    )
    for unit in found.units:
        _print_unit(unit, content, labs, today, len(found.flavors))
    if found.flavors:
        print("\nflavors (frames, files, decks):")
        width = max(len(f.name) for f in found.flavors)
        for flavor in found.flavors:
            decks = ", ".join(flavor.decks) or "no deck"
            print(
                f"  {flavor.name:<{width}}  {flavor.frames:>4}  {flavor.files:>3}  "
                f"{decks}"
            )
    if found.decks:
        print("\ndecks (the section's frames / all, how they include it):")
        width = max(len(d.deck) for d in found.decks)
        for deck in found.decks:
            share = f"{deck.frames}/{deck.total}"
            print(f"  {deck.deck:<{width}}  {share:>9}  {', '.join(deck.uses)}")
    print(
        "\nA file's diff: `deckz review diff <report> <file>`; a report's fiche: "
        "`deckz review fiche <report>`; its open findings in full: `deckz review "
        "findings <report> --text`."
    )


def _print_unit(
    unit: "BriefUnit", content: str, labs: str, today: "date", flavors: int
) -> None:
    from .status import _due, _state, _summary

    reviews = [f.review for f in unit.files]
    notebooks = [r for lab in unit.labs for r in lab.files]
    if not unit.exists:
        marked = "no report yet"
    elif unit.date is None:
        marked = "never marked"
    else:
        marked = f"marked {unit.date} ({(unit.base or '')[:8]})"
    print(
        f"\n{unit.report}: {marked}; {_summary([*reviews, *notebooks, *unit.others])}"
    )
    _print_since(unit, today)
    _print_files(unit, content, flavors)
    for lab in unit.labs:
        states = ", ".join(
            f"{Path(r.path).stem} {_state(r)}{_due(r)}" for r in lab.files
        )
        print(f"  lab {_under(lab.lab, labs)}: {states}")
    for other in unit.others:
        print(f"  other: {_state(other)}  {other.path}{_due(other)}")
    _print_findings(unit)


def _print_since(unit: "BriefUnit", today: "date") -> None:
    # When its dated facts are due, and what changed since its last mark.
    if (facts := unit.dated_facts) is not None and facts.checked is not None:
        since = "checked" if facts.source == "line" else "report added"
        due = "DUE since" if facts.due(today) else "due"
        print(f"  dated facts: {since} {facts.checked}, {due} {facts.due_on}")
    if unit.base is None:
        return
    if unit.changed is None:
        print(f"  changed since {unit.base[:8]}: unknown, not in this clone")
    elif unit.changed:
        print(f"  changed since {unit.base[:8]}: {', '.join(unit.changed)}")


def _print_files(unit: "BriefUnit", content: str, flavors: int) -> None:
    from .status import _due, _state

    if not unit.files:
        return
    width = max(len(_state(f.review)) for f in unit.files)
    print("  files (state, frames, decks, flavors):")
    for file in unit.files:
        names = ", ".join(file.flavors) or "none"
        if flavors > 1 and len(file.flavors) == flavors:
            names = "all"
        print(
            f"    {_state(file.review):<{width}}  {file.review.frames or 0:>3}  "
            f"{file.decks:>2}  {_under(file.review.path, content)}  {names}"
            f"{_due(file.review)}"
        )


def _print_findings(unit: "BriefUnit") -> None:
    # Their counts, then the open and refused ones, one line each.
    from .findings import _short

    if not unit.findings:
        return
    counts = {o: sum(f.outcome == o for f in unit.findings) for o in _OUTCOMES}
    print(
        f"  findings: {counts['open']} open, {counts['done']} done, "
        f"{counts['refused']} refused"
    )
    for finding in unit.findings:
        if finding.outcome in ("open", "refused"):
            scope = f"[{', '.join(finding.scope)}] " if finding.scope else ""
            print(
                f"    {finding.outcome:<7} {finding.id:<4} l.{finding.line:<4} "
                f"{_short(scope + finding.summary)}"
            )
