from deckz.analyzing.findings import parse
from deckz.configuring.settings import FindingsSettings

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
