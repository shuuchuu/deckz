from unittest.mock import patch

from pytest import raises

from deckz.analyzing.findings import compact, fiche, parse
from deckz.configuring.settings import FindingsSettings
from deckz.exceptions import ReviewError

GRAMMAR = FindingsSettings.model_validate(
    {
        "heading": "Findings",
        "rubrics": {"E": "Errors", "P": "Pedagogy"},
        "outcomes": {"open": "open", "done": "done", "refused": "refused"},
    }
)


def _parse(body: str) -> tuple[list[tuple[str, str | None, int]], list[str]]:
    report = parse(body, GRAMMAR, "r.md")
    return [(f.id, f.outcome, f.line) for f in report.findings], list(report.problems)


def test_an_outcome_after_a_blank_line_or_a_sub_list_is_read() -> None:
    found, problems = _parse(
        "---\nreviewed: {}\n---\n# Report\n\n## Findings\n\n### Errors\n\n"
        "- **E1** — `a.md`: wrong. *open*\n"
        "- **E2** — three versions:\n"
        "  - one;\n"
        "  - two.\n"
        "\n"
        "  Proposal: merge them.\n"
        "\n"
        "  *done* (abc123)\n"
        "- **E3** — wrapped without\n"
        "indentation *refused* (2026-11-08: why)\n"
    )

    assert found == [("E1", "open", 10), ("E2", "done", 11), ("E3", "refused", 18)]
    assert problems == []


def test_the_last_outcome_word_counts_and_bold_isnt_one() -> None:
    found, _ = _parse(
        "## Findings\n\n### Pedagogy\n\n"
        "- **P1** — *open* at first, then *done* (abc)\n"
        "- **P2** — **done** is not emphasis; *open*\n"
    )

    assert [outcome for _, outcome, _ in found] == ["done", "open"]


def test_only_items_with_an_id_under_the_heading_are_findings() -> None:
    found, problems = _parse(
        "## Summary\n\n- **E9** — not a finding *open*\n\n"
        "## Findings\n\n### Errors\n\nChecked:\n\n- the dates; *done*\n"
        "- **E1** — real *open*\n\n"
        "```\n- **E2** — in code *open*\n```\n\n"
        "#### A subdivision\n\n- **E3** — still Errors *done*\n\n"
        "## Afterwards\n\n- **E4** — outside *open*\n"
    )

    assert [(i, o) for i, o, _ in found] == [("E1", "open"), ("E3", "done")]
    assert problems == []


def test_the_summary_is_the_first_paragraph_without_the_id() -> None:
    report = parse(
        "## Findings\n\n### Errors\n\n- **E1** — `a.md`: wrong\n  and long.\n\n"
        "  *open*\n",
        GRAMMAR,
    )

    assert report.findings[0].summary == "`a.md`: wrong and long."


def test_the_grammar_problems_name_their_fix() -> None:
    _, problems = _parse(
        "## Findings\n\n### Errors\n\n"
        "- **E1** — no outcome; see P1.\n"
        "- **E1** — a second E1 *open*\n"
        "- **P2** — in the wrong rubric *open*\n"
        "- **X1** — unknown *open*\n"
        "\n### Other\n\n- **P3** — under no rubric *open*\n"
    )

    assert problems == [
        "r.md:5: E1 has no outcome: write one of *open*, *done*, *refused* in "
        "it, its last such word being the outcome",
        "r.md:6: E1 is also the id of line 5: give the newer one the next free "
        "number of its rubric (ids are never renumbered)",
        "r.md:7: P2 is under « Errors », rubric E: move it under « Pedagogy »",
        "r.md:8: X1: no rubric has the letters X (deckz.yml's "
        "`review.findings.rubrics`: E (Errors), P (Pedagogy)): give it one's "
        "letters, or add the rubric",
        "r.md:12: P3 is under « Other », which is no rubric: move it under "
        "« Pedagogy »",
    ]


def test_a_finding_keeps_its_lines_as_written() -> None:
    report = parse(
        "## Findings\n\n### Errors\n\n- **E1** — `a.md`: wrong\n  - one;\n\n"
        "  *open*\n\n- **E2** — next *done*\n",
        GRAMMAR,
    )

    first = report.findings[0]
    assert (first.line, first.end) == (5, 8)
    assert first.text == "- **E1** — `a.md`: wrong\n  - one;\n\n  *open*"


def test_the_fiche_is_the_body_before_the_findings() -> None:
    text = (
        "---\nreviewed: {}\n---\n# Report\n\n## Fiche\n\n```\n## Findings\n```\n"
        "\n| a | b |\n\n## Findings\n\n### Errors\n\n- **E1** — x *open*\n"
    )

    assert fiche(text, "Findings") == (
        "# Report\n\n## Fiche\n\n```\n## Findings\n```\n\n| a | b |\n"
    )
    assert fiche("# Only a title\n", "Findings") == "# Only a title\n"


REPORT = (
    "---\nreviewed: {}\n---\n# Report\n\n## Fiche\n\nKept.\n\n## Findings\n\n"
    "### Errors\n\nChecked: everything.\n\n"
    "- **E1** — `a.md`: still wrong. *open*\n"
    "- **E2** — three versions of the same frame:\n"
    "  - `a.md`, « Loops »;\n"
    "  - `b.md`, « Loops ».\n"
    "\n"
    "  Proposal: merge them.\n"
    "\n"
    "  *done* (4f2a9c1, 2026-11-04: merged into `a.md`, see deadbee1)\n"
    "\n"
    "### Pedagogy\n\n"
    "- **P1** [orsys/mle] — the `light` flavor is too short for this deck's\n"
    "  program. *done* (by hand, in the deck's own content)\n"
    "- **P2** — a long refusal\n  with its whole reason. *refused* (2026-11-08: why)\n"
    "- **P3** — short *done*\n"
)


def test_compact_reduces_the_done_findings_to_one_line() -> None:
    result, ids = compact(REPORT, GRAMMAR, "r.md")

    assert ids == ("E2", "P1")
    assert result == REPORT.replace(
        "- **E2** — three versions of the same frame:\n"
        "  - `a.md`, « Loops »;\n"
        "  - `b.md`, « Loops ».\n"
        "\n"
        "  Proposal: merge them.\n"
        "\n"
        "  *done* (4f2a9c1, 2026-11-04: merged into `a.md`, see deadbee1)\n",
        "- **E2** — three versions of the same frame *done* (4f2a9c1, 2026-11-04, "
        "deadbee1)\n",
    ).replace(
        "- **P1** [orsys/mle] — the `light` flavor is too short for this deck's\n"
        "  program. *done* (by hand, in the deck's own content)\n",
        "- **P1** [orsys/mle] — the `light` flavor is too short for this deck's "
        "program *done* (by hand, in the deck's own content)\n",
    )
    found = parse(result, GRAMMAR)
    assert [(f.id, f.outcome, f.scope) for f in found.findings] == [
        (f.id, f.outcome, f.scope) for f in parse(REPORT, GRAMMAR).findings
    ]
    assert found.problems == ()
    # Once compacted, there is nothing left to reduce.
    assert compact(result, GRAMMAR) == (result, ())


def test_compact_shortens_a_long_title_leaving_no_code_or_emphasis_open() -> None:
    title = "`" + "x" * 50 + "` then `horaires-*.md` and more words " * 3
    result, ids = compact(
        f"## Findings\n\n### Errors\n\n- **E1** — {title}\n  *done* (2026-11-04)\n",
        GRAMMAR,
    )

    line = result.splitlines()[-1]
    assert ids == ("E1",)
    assert line.endswith("… *done* (2026-11-04)")
    assert line.count("`") % 2 == 0
    assert len(line) < 110


def test_compact_writes_nothing_that_would_read_differently() -> None:
    text = (
        "## Findings\n\n### Errors\n\n- **E1** — x\n\n"
        "  more words than the line would have *done*\n"
    )

    with (
        patch("deckz.analyzing.findings._title", return_value="x\n\n## Other\n\n-"),
        raises(ReviewError, match="a bug of deckz"),
    ):
        compact(text, GRAMMAR, "r.md")
