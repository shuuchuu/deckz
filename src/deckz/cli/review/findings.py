from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...analyzing.findings import Finding, ReportFindings, TargetFindings
    from ...configuring.settings import FindingsSettings

_SUMMARY = 100


@app.command()
def findings(
    targets: list[Path] | None = None,
    /,
    *,
    plain: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Count the reports' findings by rubric and outcome, and list the open ones.

    A finding is a list item, under `review.findings`' heading, that starts
    with its id in bold (`**P3**`); its outcome is the last outcome word in
    it, emphasized (`*ouvert*`). The `review-findings` check fails on a
    finding that breaks this grammar (`deckz check review-findings`).

    With no TARGET, every report with findings, those with the most open
    ones first. A TARGET that is a deck's directory lists the open findings
    of its own report (its deck pass) and of the reports recording one of
    its content files, but for the findings whose scope (the decks in
    brackets after the id, `**A3** [orsys/mle]`) leaves it out, and the
    findings of any other report whose scope names it; a path under
    `review.dir` stands for the reports under it, any other path for the
    reports recording a file under it.

    Always exits 0: it only informs.

    Args:
        targets: Decks' directories or paths, from the current directory or
            the repository's root
        plain: Compact, stable lines for a script or an agent, one per
            finding of the reports shown (open or not), their fields
            separated by tabs: report, line, id, outcome (`open`, `done`,
            `refused`, or empty if it has none), summary and scope (its
            entries joined by commas, empty if it has none)
        json: Print one JSON object instead: with no TARGET, `{"reports":
            [...]}`; else `{"targets": [{target, kind ("deck" or "paths"),
            reports}]}`. A report is `{report, counts: {<letters>: {open,
            done, refused, none}}, findings: [{id, rubric, number, line,
            outcome, heading, summary, scope}]}`, every finding listed. Both have
            `problems`: the unreadable reports and the findings breaking the
            grammar
        workdir: Path to move into before running the command

    """
    from sys import stderr

    from ...analyzing.findings import findings_status
    from ...analyzing.review import locate
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = findings_status(settings, [locate(settings, t) for t in targets or ()])
    grammar = settings.review.findings
    assert grammar is not None  # `findings_status` refuses otherwise.
    if json:
        from .._presentation import print_json

        if targets:
            print_json(
                {
                    "targets": [_target_json(t, grammar) for t in found.targets],
                    "problems": list(found.problems),
                }
            )
        else:
            print_json(
                {
                    "reports": [_report_json(r, grammar) for r in found.reports],
                    "problems": list(found.problems),
                }
            )
        return
    shown = [r for t in found.targets for r in t.reports] if targets else found.reports
    if plain:
        for report in shown:
            for finding in report.findings:
                print(_plain_line(report.report, finding))
    elif targets:
        for target in found.targets:
            _print_target(target, grammar)
    else:
        _print_table(found.reports, grammar)
    for problem in found.problems:
        print(f"problem: {problem}", file=stderr)
    if found.problems and not plain:
        print("Each problem's fix: `deckz check review-findings`.", file=stderr)


def _counts(
    report: "ReportFindings", grammar: "FindingsSettings"
) -> dict[str, dict[str, int]]:
    letters = list(grammar.rubrics)
    letters += sorted({f.rubric for f in report.findings} - set(letters))
    return {
        rubric: {
            "open": report.count("open", rubric),
            "done": report.count("done", rubric),
            "refused": report.count("refused", rubric),
            "none": report.count(None, rubric),
        }
        for rubric in letters
        if any(f.rubric == rubric for f in report.findings)
    }


def _finding_json(finding: "Finding") -> dict[str, object]:
    return {
        "id": finding.id,
        "rubric": finding.rubric,
        "number": finding.number,
        "line": finding.line,
        "outcome": finding.outcome,
        "heading": finding.heading,
        "summary": finding.summary,
        "scope": list(finding.scope),
    }


def _report_json(
    report: "ReportFindings", grammar: "FindingsSettings"
) -> dict[str, object]:
    return {
        "report": report.report,
        "counts": _counts(report, grammar),
        "findings": [_finding_json(f) for f in report.findings],
    }


def _target_json(
    target: "TargetFindings", grammar: "FindingsSettings"
) -> dict[str, object]:
    return {
        "target": target.target,
        "kind": target.kind,
        "reports": [_report_json(r, grammar) for r in target.reports],
    }


def _plain_line(report: str, finding: "Finding") -> str:
    values = (report, str(finding.line), finding.id, finding.outcome or "")
    return "\t".join((*values, finding.summary, ",".join(finding.scope)))


def _short(text: str) -> str:
    return text if len(text) <= _SUMMARY else text[: _SUMMARY - 1].rstrip() + "…"


def _by_rubric(reports: "Sequence[ReportFindings]", grammar: "FindingsSettings") -> str:
    counts = [
        (letters, sum(r.count("open", letters) for r in reports))
        for letters in grammar.rubrics
    ]
    return ", ".join(f"{n} {letters}" for letters, n in counts if n)


def _print_target(target: "TargetFindings", grammar: "FindingsSettings") -> None:
    reports = target.reports
    opened = sum(r.count("open") for r in reports)
    with_open = [r for r in reports if r.count("open")]
    covering = "concerning it" if target.kind == "deck" else "it stands for"
    rubrics = f" ({_by_rubric(reports, grammar)})" if opened else ""
    print(
        f"{target.target}: {opened} open findings{rubrics}, in {len(with_open)} of "
        f"the {len(reports)} reports {covering}"
    )
    for report in with_open:
        print(f"\n  {report.report}: {report.count('open')} open")
        for finding in report.findings:
            if finding.outcome == "open":
                where = f"{finding.id:<4} l. {finding.line:<4}"
                scope = f"[{', '.join(finding.scope)}] " if finding.scope else ""
                print(f"    {where}  {_short(scope + finding.summary)}")


def _print_table(
    reports: "Sequence[ReportFindings]", grammar: "FindingsSettings"
) -> None:
    listed = sorted(
        (r for r in reports if r.findings),
        key=lambda r: (-r.count("open"), r.report),
    )
    if not listed:
        print("No report has findings.")
        return
    letters = list(grammar.rubrics)
    width = max(len("total"), *(len(r.report) for r in listed))
    total_open = sum(r.count("open") for r in listed)
    rubric_width = max(*(len(letter) for letter in letters), len(str(total_open))) + 1
    header = "".join(f"{letter:>{rubric_width}}" for letter in letters)
    print(f"{'report':<{width}}  {'open':>4} {header}  {'done':>5}  {'refused':>7}")

    def row(name: str, group: "Sequence[ReportFindings]") -> str:
        cells = "".join(
            f"{sum(r.count('open', letter) for r in group):>{rubric_width}}"
            for letter in letters
        )
        opened = sum(r.count("open") for r in group)
        done = sum(r.count("done") for r in group)
        refused = sum(r.count("refused") for r in group)
        return f"{name:<{width}}  {opened:>4} {cells}  {done:>5}  {refused:>7}"

    for report in listed:
        print(row(report.report, [report]))
    print(row("total", listed))
    rubrics = ", ".join(f"{k} {v}" for k, v in grammar.rubrics.items())
    print(
        f"\n{len(listed)} reports with findings, of {len(reports)}. The open "
        f"findings by rubric ({rubrics}). A deck's open findings: `deckz review "
        "findings <deck>`."
    )
