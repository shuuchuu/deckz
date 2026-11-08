import subprocess
from datetime import UTC, date
from json import loads
from pathlib import Path
from shutil import copytree
from typing import Any

from pytest import fixture, raises

from deckz.analyzing.review import (
    diff,
    header_problems,
    mark,
    read_report,
    review_status,
)
from deckz.cli import main
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.exceptions import DeckParsingError, ReviewError
from deckz.status import deck_status

REPORT = "reviews/sections/sec.md"
A = "content/sec/a.md"
B = "content/sec/b.md"
C = "content/sec/sub/c.md"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def _commit(repo: Path, message: str, *paths: str) -> None:
    _git(repo, "add", "--", *(paths or (".",)))
    _git(repo, "commit", "--quiet", "-m", message)


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    # test_cli's repository, with a shared section `sec` (and its subsection
    # `sec/sub`) that two decks use: `company/abc` its `light` flavor (a.md),
    # `company/two` its `full` one (a.md, b.md, sub/c.md).
    import appdirs

    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (root / "user-variables.yml").rename(user_dir / "variables.yml")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    deckz_yml = root / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8") + "review:\n  dir: reviews\n",
        encoding="utf8",
    )
    _write(
        root / "content" / "sec" / "sec.yml",
        "title: Sec\nflavors:\n"
        "  - name: full\n    includes: [a, b, $sub@full]\n"
        "  - name: light\n    includes: [a]\n",
    )
    _write(root / "content" / "sec" / "a.md", "# A1\n\nText.\n\n# A2\n\nMore.\n")
    _write(root / "content" / "sec" / "b.md", "# B\n\n```\n# not a frame\n```\n")
    _write(root / "content" / "sec" / "en" / "a.md", "# A1\n\n# A2\n")
    _write(
        root / "content" / "sec" / "sub" / "sub.yml",
        "title: Sub\nflavors:\n  - name: full\n    includes: [c]\n",
    )
    _write(root / "content" / "sec" / "sub" / "c.md", "# C1\n\n# C2\n\n# C3\n")
    _write(
        root / "company" / "two" / "deck.yml",
        "name: TWO\nparts:\n  - name: only\n    sections:\n      - $sec@full\n",
    )
    abc = root / "company" / "abc" / "deck.yml"
    abc.write_text(
        abc.read_text(encoding="utf8") + "      - $sec@light\n", encoding="utf8"
    )
    _write(root / "labs" / "notebooks" / "sec" / "lab-fr.ipynb", "{}\n")
    _git(root, "init", "--quiet", "-b", "main")
    _commit(root, "Start")
    monkeypatch.chdir(root)
    return root


def _settings(path: Path) -> GlobalSettings:
    return GlobalSettings.from_yaml(path)


def _blob(repo: Path, path: str) -> str:
    return _git(repo, "hash-object", path)


def _mark(repo: Path, *paths: str, **kwargs: Any) -> Any:
    return mark(
        _settings(repo),
        repo / REPORT,
        [repo / path for path in paths],
        accept=[repo / path for path in kwargs.pop("accept", ())],
        forget=[repo / path for path in kwargs.pop("forget", ())],
        **kwargs,
    )


def _states(repo: Path, *targets: str) -> dict[str, tuple[str, Any, Any]]:
    found = review_status(_settings(repo), [repo / target for target in targets])
    return {
        review.path: (review.state, review.added, review.removed)
        for target in found.targets
        for review in (
            target.files
            if target.deck is None
            else [r for s in target.deck.sections for r in s.files]
        )
    }


def test_mark_creates_the_report_with_each_files_blob(repo: Path) -> None:
    result = _mark(repo, "content/sec", today=date(2026, 10, 23))

    assert result.created
    assert result.added == (A, B, C)
    report = read_report(_settings(repo), repo / REPORT)
    assert report.date == date(2026, 10, 23)
    assert report.base == _git(repo, "rev-parse", "HEAD")
    assert report.files == {path: _blob(repo, path) for path in (A, B, C)}
    text = (repo / REPORT).read_text(encoding="utf8")
    assert text.startswith("---\nreviewed:\n  date: 2026-10-23\n")
    assert text.endswith("---\n")


def test_a_content_directory_stands_for_the_files_decks_include(repo: Path) -> None:
    _write(repo / "content" / "sec" / "reserve.md", "# Unused\n")

    result = _mark(repo, "content/sec")

    # Neither the file no deck includes, nor the en/ translation.
    assert result.added == (A, B, C)


def test_mark_rewrites_only_the_reviewed_key(repo: Path) -> None:
    head = "---\ntitle: Sec\nreviewed:\n  date: 2020-01-01\n"
    head += f"  base: {'a' * 40}\n  files: {{}}\n\nowner: me\n---\n"
    body = "# Fiche\n\nKept   as is.\n---\nnot front matter\n"
    _write(repo / REPORT, head + body)

    _mark(repo, A)

    text = (repo / REPORT).read_text(encoding="utf8")
    assert text.startswith("---\ntitle: Sec\nreviewed:\n")
    assert text.endswith("\nowner: me\n---\n" + body)
    assert read_report(_settings(repo), repo / REPORT).files == {A: _blob(repo, A)}


def test_mark_adds_front_matter_to_a_report_without_one(repo: Path) -> None:
    _write(repo / REPORT, "# Fiche\n")

    _mark(repo, B)

    text = (repo / REPORT).read_text(encoding="utf8")
    assert text.startswith("---\nreviewed:\n")
    assert text.endswith("---\n# Fiche\n")


def test_mark_refuses_a_report_outside_the_review_dir(repo: Path) -> None:
    with raises(ReviewError, match=r"\(`review\.dir`\)"):
        mark(_settings(repo), repo / "docs" / "sec.md", [repo / A])


def test_review_commands_need_the_review_dir(repo: Path) -> None:
    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8").replace("review:\n  dir: reviews\n", ""),
        encoding="utf8",
    )

    with raises(ReviewError, match=r"set `review.dir` in deckz.yml"):
        review_status(_settings(repo), [])
    assert header_problems(_settings(repo), None) == []


def test_status_tells_fresh_stale_and_unreviewed_files(repo: Path) -> None:
    _mark(repo, A, B)
    _write(repo / B, "# B\n\nchanged\n\nmore\n")

    states = _states(repo, "content/sec")

    assert states == {
        A: ("fresh", None, None),
        B: ("stale", 3, 3),
        C: ("unreviewed", None, None),
    }


def test_status_of_a_deck_groups_its_files_and_the_reports_other_files(
    repo: Path,
) -> None:
    notebook = "labs/notebooks/sec/lab-fr.ipynb"
    _mark(repo, A, notebook)

    found = review_status(_settings(repo), [repo / "company" / "two"])

    deck = found.targets[0].deck
    assert deck is not None
    assert [(s.section, [r.path for r in s.files]) for s in deck.sections] == [
        ("sec", [A, B]),
        ("sec/sub", [C]),
    ]
    assert [(r.path, r.state, r.report) for r in deck.others] == [
        (notebook, "fresh", REPORT)
    ]


def test_the_most_recent_mark_wins(repo: Path) -> None:
    other = repo / "reviews" / "sections" / "deep" / "other.md"
    mark(_settings(repo), other, [repo / A], today=date(2026, 1, 1))
    _write(repo / A, "# A changed\n")
    _mark(repo, A, today=date(2026, 2, 1))

    found = review_status(_settings(repo), [repo / A])

    review = found.targets[0].files[0]
    assert review.state == "fresh"
    assert [m.report for m in review.marks] == [
        REPORT,
        "reviews/sections/deep/other.md",
    ]


def test_status_ranks_sections_by_decks_times_frames_to_review(repo: Path) -> None:
    ranked = {r.section: r for r in review_status(_settings(repo), []).ranked}

    # sec: a.md (2 frames) in 2 decks, b.md (1) in one; sec/sub: c.md (3).
    assert (ranked["sec"].decks, ranked["sec"].frames, ranked["sec"].score) == (
        2,
        3,
        6,
    )
    assert ranked["sec/sub"].score == 3
    order = [r.section for r in review_status(_settings(repo), []).ranked]
    assert order.index("sec") < order.index("sec/sub")

    _mark(repo, A)
    ranked = {r.section: r for r in review_status(_settings(repo), []).ranked}
    assert ranked["sec"].score == 2
    assert ranked["sec"].count("fresh") == 1
    assert ranked["sec"].reports == (REPORT,)


def test_a_stale_file_counts_the_frames_its_changes_touch(repo: Path) -> None:
    _write(repo / A, "# A1\n\nOne.\n\n# A2\n\nTwo.\n\n# A3\n\nThree.\n")
    _commit(repo, "three frames", A)
    _mark(repo, A)

    def changed() -> int | None:
        found = review_status(_settings(repo), [repo / A])
        return found.targets[0].files[0].changed_frames

    _write(repo / A, "# A1\n\nOne.\n\n# A2\n\nTwo, changed.\n\n# A3\n\nThree.\n")
    assert changed() == 1
    _write(repo / A, "# A1\n\nOne.\n\n# A2\n\nTwo.\n\nMore.\n\n# A3\n\nThree.\n")
    assert changed() == 1
    _write(repo / A, "# A1\n\nOne.\n")
    assert changed() == 2
    _write(repo / A, "# A1\n\nOne!\n\n# A2\n\nTwo.\n\n# A3\n\nThree!\n")
    assert changed() == 2
    ranked = {r.section: r for r in review_status(_settings(repo), []).ranked}
    # b.md (1 frame), unreviewed, counts whole; a.md its 2 changed frames.
    assert (ranked["sec"].frames, ranked["sec"].score) == (3, 6)


def test_diff_shows_what_changed_since_the_review(repo: Path) -> None:
    _mark(repo, A, B, C)
    _write(repo / A, "# A1\n\nText changed.\n\n# A2\n\nMore.\n")
    (repo / C).unlink()

    found = {f.path: f for f in diff(_settings(repo), repo / REPORT)}

    assert set(found) == {A, C}
    assert found[A].state == "stale"
    assert (found[A].added, found[A].removed) == (1, 1)
    text = found[A].diff or ""
    assert f"+++ b/{A}" in text
    assert "-Text.\n+Text changed.\n" in text
    assert found[C].state == "deleted"
    assert [f.path for f in diff(_settings(repo), repo / REPORT, [repo / A])] == [A]


def test_mark_with_no_path_refreshes_every_recorded_file(repo: Path) -> None:
    _mark(repo, A, B)
    _write(repo / A, "# A changed\n")

    result = _mark(repo)

    assert result.refreshed == (A,)
    assert result.unchanged == (B,)
    assert _states(repo, A) == {A: ("fresh", None, None)}


def test_forget_alone_refreshes_nothing(repo: Path) -> None:
    _mark(repo, A, B)
    _write(repo / A, "# A changed\n")

    result = _mark(repo, forget=[B])

    assert result.forgotten == (B,)
    assert result.refreshed == ()
    assert _states(repo, A) == {A: ("stale", 1, 7)}


def test_forget_old_with_new_carries_a_rename(repo: Path) -> None:
    _mark(repo, A, B)
    _git(repo, "mv", B, "content/sec/b2.md")
    assert header_problems(_settings(repo), None) == [
        f"{REPORT}: records {B}, which doesn't exist: if it was renamed, "
        f"`deckz review mark {REPORT} --forget {B} <new path>`, else `--forget` "
        "it alone"
    ]

    result = _mark(repo, "content/sec/b2.md", forget=[B])

    assert result.forgotten == (B,)
    assert result.added == ("content/sec/b2.md",)
    assert header_problems(_settings(repo), None) == []


def test_mark_refuses_a_missing_file(repo: Path) -> None:
    result = _mark(repo, "content/sec/gone.md")

    assert result.refused[0][0] == "content/sec/gone.md"
    assert "--forget content/sec/gone.md" in result.refused[0][1]
    assert not (repo / REPORT).exists()


def _worktree(repo: Path) -> Path:
    path = repo.parent / "repo--ws"
    _git(repo, "worktree", "add", "--quiet", "-b", "ws/x", str(path))
    return path


def test_mark_refuses_changes_from_the_main_branch(repo: Path) -> None:
    _mark(repo, A, B)
    reviewed = _blob(repo, A)
    _commit(repo, "Review sec", REPORT)
    worktree = _worktree(repo)
    # Another session lands a change to a.md...
    _write(repo / A, "# A1\n\nSomeone else's change.\n")
    _commit(repo, "Elsewhere", A)
    # ...this branch picks it up, and changes b.md itself.
    _git(worktree, "rebase", "--quiet", "main")
    _write(worktree / B, "# B\n\nMine.\n")
    _commit(worktree, "Mine", B)

    result = _mark(worktree)

    assert result.refreshed == (B,)
    assert [path for path, _ in result.refused] == [A]
    reason = result.refused[0][1]
    assert "commits from main" in reason
    assert f"deckz review diff {REPORT} {A}" in reason
    assert f"deckz review mark {REPORT} --accept {A}" in reason
    recorded = read_report(_settings(worktree), worktree / REPORT).files
    assert recorded[A] == reviewed
    assert recorded[B] == _blob(worktree, B)

    accepted = _mark(worktree, accept=[A])

    assert accepted.refreshed == (A,)
    assert accepted.refused == ()


def test_mark_takes_the_branchs_own_changes_since_an_earlier_mark(
    repo: Path,
) -> None:
    worktree = _worktree(repo)
    _write(worktree / A, "# A1\n\nFirst pass.\n")
    _commit(worktree, "First", A)
    _mark(worktree, A)
    _write(worktree / A, "# A1\n\nSecond pass.\n")
    _commit(worktree, "Second", A)
    _write(worktree / A, "# A1\n\nThird pass, not committed.\n")

    result = _mark(worktree, A)

    assert result.refreshed == (A,)
    assert result.refused == ()


def test_on_the_main_branch_without_upstream_only_uncommitted_changes_pass(
    repo: Path,
) -> None:
    _mark(repo, A, B)
    _write(repo / A, "# A changed\n")
    _write(repo / B, "# B changed\n")
    _commit(repo, "Change b", B)

    result = _mark(repo)

    assert result.refreshed == (A,)
    assert [path for path, _ in result.refused] == [B]


def test_the_check_reports_malformed_headers(repo: Path) -> None:
    _write(
        repo / "reviews" / "sections" / "bad.md",
        "---\nreviewed:\n  date: soon\n  base: abc\n  files:\n    x.md: 12\n---\n",
    )
    _write(repo / "reviews" / "sections" / "unclosed.md", "---\nreviewed: {}\n")
    _write(
        repo / "reviews" / "sections" / "fine.md",
        "# No front matter: nothing recorded\n",
    )

    problems = header_problems(_settings(repo), None)

    assert len(problems) == 2
    bad = next(p for p in problems if p.startswith("reviews/sections/bad.md"))
    assert "`reviewed.date` is not a date" in bad
    assert "`reviewed.base` is not a commit sha" in bad
    assert "x.md is not a blob sha" in bad
    assert any("no closing `---`" in p for p in problems)
    assert (
        header_problems(_settings(repo), [repo / "reviews" / "sections" / "fine.md"])
        == []
    )


def test_the_check_runs_from_deckz_check(repo: Path, capsys: Any) -> None:
    _write(repo / "reviews" / "sections" / "bad.md", "---\nreviewed: [1]\n---\n")

    with raises(SystemExit) as exc_info:
        main(("check", "review-headers"))

    assert exc_info.value.code == 1
    assert "`reviewed` is not a mapping" in capsys.readouterr().out


def test_cli_mark_exits_1_on_a_refusal(repo: Path, capsys: Any) -> None:
    main(("review", "mark", REPORT, A, "--json"))
    assert loads(capsys.readouterr().out)["added"] == [A]
    _commit(repo, "Review", REPORT)
    _write(repo / A, "# A changed\n")
    _commit(repo, "Change", A)

    with raises(SystemExit) as exc_info:
        main(("review", "mark", REPORT))

    assert exc_info.value.code == 1
    assert "refused: " in capsys.readouterr().out


def test_cli_status_and_diff(repo: Path, capsys: Any) -> None:
    main(("review", "mark", REPORT, "content/sec"))
    capsys.readouterr()
    _write(repo / B, "# B\n\nchanged\n")

    main(("review", "status", "company/two", "--json"))
    report = loads(capsys.readouterr().out)
    files = {f["path"]: f for s in report["targets"][0]["sections"] for f in s["files"]}
    assert files[B]["state"] == "stale"
    assert files[A]["reports"][0]["report"] == REPORT

    main(("review", "status", "--plain"))
    lines = capsys.readouterr().out.splitlines()
    assert any(line.split("\t")[1] == "sec" for line in lines)

    main(("review", "diff", REPORT, "--stat"))
    assert capsys.readouterr().out == f"{B}\t+1\t-3\n"


def test_deckz_status_counts_a_decks_content_not_reviewed(repo: Path) -> None:
    _mark(repo, A)

    _, sections = deck_status(
        DeckSettings.from_yaml(repo / "company" / "two"), checks=False, decks=False
    )

    review = next(s for s in sections if s.key == "review")
    assert len(review.items) == 1
    assert review.items[0].text == (
        "company/two: of its 3 content files, 2 never reviewed"
    )
    assert review.items[0].fix == "`deckz review status company/two` lists them"


def test_a_deck_that_doesnt_parse_fails_the_ranking_at_once(repo: Path) -> None:
    # Decks parse in a process pool: the error must survive being sent back.
    _write(
        repo / "company" / "two" / "deck.yml",
        "name: TWO\nparts:\n  - name: only\n    sections:\n      - $sec@nope\n",
    )

    with raises(DeckParsingError, match="deck parsing failed"):
        review_status(_settings(repo), [])


def test_deps_json_gives_each_flavors_files_and_dependents(
    repo: Path, capsys: Any
) -> None:
    main(("deps", "sec", "--json"))
    report = loads(capsys.readouterr().out)

    assert report["flavors"] == {
        "full": {
            "files": {A: 2, B: 1, C: 3},
            "dependents": {"company/two": ["only"]},
        },
        "light": {"files": {A: 2}, "dependents": {"company/abc": ["p2"]}},
    }
    assert report["deck_frames"]["company/two"] == 6
    assert set(report["deck_frames"]) == {"company/abc", "company/two"}
    assert report["dependents"] == {"company/abc": ["p2"], "company/two": ["only"]}

    main(("deps", "sec", "light", "--json"))
    assert list(loads(capsys.readouterr().out)["flavors"]) == ["light"]


FINDINGS = (
    "review:\n  dir: reviews\n  findings:\n    heading: Findings\n"
    "    rubrics: {E: Errors, P: Pedagogy}\n"
    "    outcomes: {open: open, done: done, refused: refused}\n"
)
OTHER = "reviews/sections/other.md"


def test_cli_findings_of_every_report_and_of_a_deck(repo: Path, capsys: Any) -> None:
    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8").replace(
            "review:\n  dir: reviews\n", FINDINGS
        ),
        encoding="utf8",
    )
    main(("review", "mark", REPORT, C))
    main(("review", "mark", OTHER, "labs/notebooks/sec"))
    capsys.readouterr()
    for report in (REPORT, OTHER):
        path = repo / report
        path.write_text(
            path.read_text(encoding="utf8")
            + "\n## Findings\n\n### Errors\n\n- **E1** — `c.md`: wrong. *open*\n"
            "\n### Pedagogy\n\n- **P1** — fixed. *done* (abc)\n",
            encoding="utf8",
        )

    main(("review", "findings", "--json"))
    found = loads(capsys.readouterr().out)
    assert [r["report"] for r in found["reports"]] == [OTHER, REPORT]
    assert found["reports"][1]["counts"] == {
        "E": {"open": 1, "done": 0, "refused": 0, "none": 0},
        "P": {"open": 0, "done": 1, "refused": 0, "none": 0},
    }
    assert found["problems"] == []

    # company/two includes c.md, which only `REPORT` records.
    main(("review", "findings", "company/two"))
    out = capsys.readouterr().out
    assert out.startswith(
        "company/two: 1 open findings (1 E), in 1 of the 1 reports concerning it"
    )
    assert f"  {REPORT}: 1 open\n    E1   l. " in out

    # Any other path: the reports recording a file under it.
    main(("review", "findings", "labs", "--plain"))
    fields = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [(f[0], f[2], f[3], f[4]) for f in fields] == [
        (OTHER, "E1", "open", "`c.md`: wrong. *open*"),
        (OTHER, "P1", "done", "fixed. *done* (abc)"),
    ]


def test_a_scoped_finding_counts_for_the_decks_it_names(
    repo: Path, capsys: Any
) -> None:
    from deckz.analyzing.findings import findings_problems

    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8").replace(
            "review:\n  dir: reviews\n", FINDINGS
        ),
        encoding="utf8",
    )
    # a.md is in both decks: company/abc (`light`) and company/two (`full`).
    main(("review", "mark", REPORT, A))
    path = repo / REPORT
    path.write_text(
        path.read_text(encoding="utf8")
        + "\n## Findings\n\n### Errors\n\n- **E1** — `a.md`: wrong. *open*\n"
        "\n### Pedagogy\n\n"
        "- **P1** [abc] — `light` too short for it. *open*\n"
        "- **P2** [company/two] — `full` too long for it. *open*\n"
        "- **P3** [company/gone] — a past session's. *refused* (gone)\n",
        encoding="utf8",
    )
    capsys.readouterr()

    main(("review", "findings", "company/abc", "--plain"))
    fields = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [(f[2], f[4], f[5]) for f in fields] == [
        ("E1", "`a.md`: wrong. *open*", ""),
        ("P1", "`light` too short for it. *open*", "abc"),
    ]
    main(("review", "findings", DECK, "--plain"))
    fields = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [f[2] for f in fields] == ["E1", "P2"]
    # The section's own view keeps every finding.
    main(("review", "findings", REPORT, "--plain"))
    assert len(capsys.readouterr().out.splitlines()) == 4

    main(("dashboard", "--json"))
    rows = {d["deck"]: d for d in loads(capsys.readouterr().out)["decks"]}
    assert rows["company/abc"]["levels"]["findings"]["open"] == {"E": 1, "P": 1}
    assert rows[DECK]["levels"]["findings"]["open"] == {"E": 1, "P": 1}

    assert findings_problems(_settings(repo), None) == []
    path.write_text(
        path.read_text(encoding="utf8") + "- **P4** [nowhere] — typo. *open*\n",
        encoding="utf8",
    )
    _write(
        repo / DECK_REPORT,
        "# QA\n\n## Findings\n\n### Errors\n\n- **E1** [abc] — not its own. *open*\n",
    )
    problems = findings_problems(_settings(repo), None)
    assert len(problems) == 2
    assert "has a scope, in a deck's report" in problems[0]
    assert "« nowhere » names no deck" in problems[1]


def test_a_scope_entry_names_a_deck_by_its_directory_or_its_end() -> None:
    from deckz.analyzing.findings import resolve_scope

    decks = ("decks/eni/ml1", "decks/orsys/ml1", "decks/orsys/mle")
    assert resolve_scope("orsys/mle", decks) == ("decks/orsys/mle",)
    assert resolve_scope("decks/orsys/mle", decks) == ("decks/orsys/mle",)
    assert resolve_scope("ml1", decks) == ("decks/eni/ml1", "decks/orsys/ml1")
    assert resolve_scope("rsys/mle", decks) == ()


def test_cli_findings_refuses_without_a_grammar(repo: Path, caplog: Any) -> None:
    with raises(SystemExit) as exc_info:
        main(("review", "findings"))

    assert exc_info.value.code == 1
    assert "set `review.findings` in deckz.yml" in caplog.text


DECK = "company/two"
DECK_REPORT = "reviews/company/two.md"
DECK_FILES = (
    "company/two/content/local.md",
    "company/two/deck.yml",
    "company/two/program.md",
)


def _deck_repo(repo: Path) -> Path:
    # company/two gets its own files: a program, a deck-local content file
    # and English translations of both, which a deck report leaves out.
    _write(repo / DECK / "program.md", "# Program\n")
    _write(repo / DECK / "en" / "program.md", "# Program\n")
    _write(repo / DECK / "content" / "local.md", "# Local\n")
    _write(repo / DECK / "content" / "en" / "local.md", "# Local\n")
    _commit(repo, "Deck files", DECK)
    return repo


def test_a_reports_kind_comes_from_its_path(repo: Path) -> None:
    from deckz.analyzing.review import report_kind

    settings = _settings(repo)

    assert report_kind(settings, repo / REPORT) == ("section", None)
    assert report_kind(settings, repo / DECK_REPORT) == ("deck", DECK)
    assert report_kind(settings, repo / "reviews" / "company" / "gone.md") is None
    assert report_kind(settings, repo / "reviews" / "loose.md") is None


def test_the_check_and_mark_refuse_a_misplaced_report(repo: Path) -> None:
    _write(repo / "reviews" / "loose.md", "# Nothing recorded\n")

    problems = header_problems(_settings(repo), None)

    assert len(problems) == 1
    assert problems[0].startswith("reviews/loose.md is neither")
    assert "reviews/sections/" in problems[0]
    with raises(ReviewError, match="is neither a shared section's report"):
        mark(_settings(repo), repo / "reviews" / "company" / "gone.md", [repo / A])


def test_a_deck_report_records_the_decks_own_files(repo: Path) -> None:
    _deck_repo(repo)
    report = repo / DECK_REPORT

    result = mark(_settings(repo), report, [], today=date(2026, 11, 8))

    assert result.created
    assert result.added == DECK_FILES
    # Its directory stands for the same files, not for the deck's content.
    _write(repo / DECK / "variables.yml", "x: 1\n")
    result = mark(_settings(repo), report, [repo / DECK])
    assert result.added == ("company/two/variables.yml",)
    assert result.refused == ()


def test_a_deck_report_refuses_shared_content(repo: Path) -> None:
    _deck_repo(repo)

    result = mark(_settings(repo), repo / DECK_REPORT, [repo / A, repo / DECK])

    assert [path for path, _ in result.refused] == [A]
    assert "review it in its section's report" in result.refused[0][1]
    assert set(read_report(_settings(repo), repo / DECK_REPORT).files) == set(
        DECK_FILES
    )


def test_a_decks_status_shows_its_pass(repo: Path) -> None:
    _deck_repo(repo)

    def deck_pass() -> Any:
        found = review_status(_settings(repo), [repo / DECK])
        deck = found.targets[0].deck
        assert deck is not None
        return deck

    assert deck_pass().deck_pass.date is None
    assert not deck_pass().deck_pass.holds
    assert deck_pass().deck_pass.report == DECK_REPORT
    mark(_settings(repo), repo / DECK_REPORT, [], today=date(2026, 11, 8))
    deck = deck_pass()
    assert deck.deck_pass.holds
    assert deck.others == ()  # its own files show in its pass only
    _write(repo / DECK / "program.md", "# Program, changed\n")
    _write(repo / DECK / "content" / "new.md", "# New\n")
    states = {r.path: r.state for r in deck_pass().deck_pass.files}
    assert not deck_pass().deck_pass.holds
    assert states["company/two/program.md"] == "stale"
    assert states["company/two/content/new.md"] == "unreviewed"
    assert states["company/two/deck.yml"] == "fresh"


def test_mark_at_records_a_past_commits_versions(repo: Path) -> None:
    _deck_repo(repo)
    past = _git(repo, "rev-parse", "HEAD")
    _write(repo / DECK / "program.md", "# Program, changed\n")
    _write(repo / DECK / "content" / "new.md", "# New\n")
    _commit(repo, "Later", DECK)

    result = mark(_settings(repo), repo / DECK_REPORT, [], at=past[:10])

    assert result.added == DECK_FILES
    report = read_report(_settings(repo), repo / DECK_REPORT)
    assert report.base == past
    assert report.date == date.fromisoformat(
        _git(repo, "show", "-s", "--format=%cs", past)
    )
    assert report.files["company/two/program.md"] == _git(
        repo, "rev-parse", f"{past}:company/two/program.md"
    )
    deck = review_status(_settings(repo), [repo / DECK]).targets[0].deck
    assert deck is not None
    states = {r.path: r.state for r in deck.deck_pass.files}
    assert states["company/two/program.md"] == "stale"
    assert states["company/two/content/new.md"] == "unreviewed"


def test_mark_at_refuses_what_it_cant_register(repo: Path) -> None:
    _deck_repo(repo)
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    settings = _settings(repo)

    with raises(ReviewError, match="is not a commit"):
        mark(settings, repo / REPORT, [repo / A], at="nowhere")
    with raises(ReviewError, match=r"not in .*company/two/program\.md"):
        mark(settings, repo / DECK_REPORT, [repo / DECK / "program.md"], at=first)
    _git(repo, "checkout", "--quiet", "-b", "side")
    _git(repo, "commit", "--quiet", "--allow-empty", "-m", "Side")
    side = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--quiet", "main")
    with raises(ReviewError, match="not in this branch's history"):
        mark(settings, repo / REPORT, [repo / A], at=side)
    mark(settings, repo / REPORT, [repo / A])
    with raises(ReviewError, match=r"already records content/sec/a\.md"):
        mark(settings, repo / REPORT, [repo / A], at=first)


def test_a_decks_findings_include_its_report(repo: Path, capsys: Any) -> None:
    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text(encoding="utf8").replace(
            "review:\n  dir: reviews\n", FINDINGS
        ),
        encoding="utf8",
    )
    main(("review", "mark", DECK_REPORT))
    path = repo / DECK_REPORT
    path.write_text(
        path.read_text(encoding="utf8")
        + "\n## Findings\n\n### Errors\n\n- **E1** — budget. *open*\n",
        encoding="utf8",
    )
    capsys.readouterr()

    main(("review", "findings", DECK, "--plain"))

    fields = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert [(f[0], f[2], f[3]) for f in fields] == [(DECK_REPORT, "E1", "open")]


def test_cli_status_of_a_deck_shows_its_pass(repo: Path, capsys: Any) -> None:
    main(("review", "status", DECK))
    assert "Deck pass: none recorded" in capsys.readouterr().out

    main(("review", "mark", DECK_REPORT))
    capsys.readouterr()
    main(("review", "status", DECK, "--json"))
    deck_pass = loads(capsys.readouterr().out)["targets"][0]["deck_pass"]
    assert deck_pass["report"] == DECK_REPORT
    assert deck_pass["holds"] is True
    assert [f["path"] for f in deck_pass["files"]] == ["company/two/deck.yml"]

    main(("review", "status", DECK, "--plain"))
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].split("\t") == [
        "fresh",
        "company/two/deck.yml",
        "",
        "",
        DECK_REPORT,
    ]


def _with_settings(repo: Path, text: str) -> None:
    deckz_yml = repo / "deckz.yml"
    deckz_yml.write_text(deckz_yml.read_text(encoding="utf8") + text, encoding="utf8")


def test_a_partial_mark_keeps_the_other_files_day(repo: Path) -> None:
    _mark(repo, A, B, today=date(2026, 10, 1))
    first = read_report(_settings(repo), repo / REPORT)

    _mark(repo, A, today=date(2026, 11, 8))

    report = read_report(_settings(repo), repo / REPORT)
    assert report.date == date(2026, 11, 8)
    assert report.own == {B: (date(2026, 10, 1), first.base)}
    assert A not in report.own
    text = (repo / REPORT).read_text(encoding="utf8")
    assert f"    {B}:\n      blob: {_blob(repo, B)}\n      date: 2026-10-01\n" in text
    marks = review_status(_settings(repo), [repo / B]).targets[0].files[0].marks
    assert marks[0].date == date(2026, 10, 1)
    # Marking it again gives it the report's day back, and the plain form.
    _mark(repo, B, today=date(2026, 11, 8))
    assert read_report(_settings(repo), repo / REPORT).own == {}
    assert f"  {B}: {_blob(repo, B)}\n" in (repo / REPORT).read_text(encoding="utf8")


def test_a_malformed_own_entry_is_a_header_problem(repo: Path) -> None:
    _mark(repo, A, today=date(2026, 11, 8))
    path = repo / REPORT
    path.write_text(
        path.read_text(encoding="utf8").replace(
            f"{A}: {_blob(repo, A)}",
            f"{A}:\n      blob: {_blob(repo, A)}\n      date: x",
        ),
        encoding="utf8",
    )

    problems = header_problems(_settings(repo), None)

    assert len(problems) == 1
    assert "`date` is not a date" in problems[0]
    assert "`base` is not a commit sha" in problems[0]


def test_mark_at_adds_files_to_a_report_with_their_own_day(repo: Path) -> None:
    past = _git(repo, "rev-parse", "HEAD")
    _write(repo / B, "# B, changed\n")
    _commit(repo, "Later", B)
    _mark(repo, A, today=date(2030, 1, 1))

    result = _mark(repo, B, at=past)

    assert result.added == (B,)
    report = read_report(_settings(repo), repo / REPORT)
    day = date.fromisoformat(_git(repo, "show", "-s", "--format=%cs", past))
    assert report.date == date(2030, 1, 1)
    assert report.own == {B: (day, past)}
    assert report.files[B] == _git(repo, "rev-parse", f"{past}:{B}")
    assert _states(repo, B)[B][0] == "stale"


def test_a_rule_makes_files_marked_before_it_due(repo: Path, capsys: Any) -> None:
    _with_settings(
        repo,
        "  rules:\n    - paths: content/sec/*.md\n      since: 2026-10-23\n"
        "      why: the new rule\n",
    )
    _mark(repo, A, B, C, today=date(2026, 10, 1))
    _write(repo / B, "# B, changed\n")

    found = review_status(_settings(repo), [repo / "content" / "sec"]).targets[0]
    by_path = {review.path: review for review in found.files}
    assert by_path[A].state == "due"
    assert [rule.why for rule in by_path[A].due] == ["the new rule"]
    assert by_path[B].state == "stale"
    assert [rule.why for rule in by_path[B].due] == ["the new rule"]
    assert by_path[C].state == "fresh"  # sub/c.md: `*` doesn't cross directories
    ranked = {r.section: r for r in review_status(_settings(repo), []).ranked}
    assert ranked["sec"].count("due") == 1
    assert ranked["sec"].frames == 2 + 1  # a.md and b.md whole

    main(("review", "status", "content/sec"))
    out = capsys.readouterr().out
    assert "due since 2026-10-23: the new rule" in out
    assert "review it against the rule" in out

    _mark(repo, A, today=date(2026, 11, 8))
    assert _states(repo, A)[A][0] == "fresh"


def test_course_notes_reports_and_chapters(repo: Path, capsys: Any) -> None:
    chapter = "course-notes/sec/a.md"
    _write(repo / chapter, "# A\n\nThe chapter.\n")
    _write(repo / "course-notes" / "sec" / "en" / "a.md", "# A\n")
    _write(repo / "course-notes" / "CLAUDE.md", "Notes for agents.\n")
    notes_report = "reviews/course-notes/sec.md"

    result = mark(
        _settings(repo),
        repo / notes_report,
        [repo / "course-notes"],
        today=date(2026, 11, 8),
    )

    assert result.added == (chapter,)
    assert header_problems(_settings(repo), None) == []
    deck = review_status(_settings(repo), [repo / "company" / "two"]).targets[0].deck
    assert deck is not None
    assert [(r.path, r.state) for r in deck.chapters] == [(chapter, "fresh")]
    assert chapter not in {r.path for r in deck.others}
    main(("review", "status", "company/two", "--json"))
    target = loads(capsys.readouterr().out)["targets"][0]
    assert [c["path"] for c in target["chapters"]] == [chapter]


def test_a_rule_since_a_time_compares_the_marks_commit(repo: Path) -> None:
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    _with_settings(
        repo,
        "  rules:\n"
        f"    - paths: '{A}'\n      since: {(now - timedelta(hours=1)).isoformat()}\n"
        "      why: older than the base\n"
        f"    - paths: '{A}'\n      since: {(now + timedelta(hours=1)).isoformat()}\n"
        "      why: newer than the base\n",
    )
    _mark(repo, A, today=now.date())

    review = _states_reviews(repo, A)[A]

    assert review.state == "due"
    assert [rule.why for rule in review.due] == ["newer than the base"]


def _states_reviews(repo: Path, *targets: str) -> dict[str, Any]:
    found = review_status(_settings(repo), [repo / target for target in targets])
    return {review.path: review for target in found.targets for review in target.files}


def test_mark_at_follows_a_rename_since_the_commit(repo: Path) -> None:
    past = _git(repo, "rev-parse", "HEAD")
    moved = "content/sec/moved.md"
    _git(repo, "mv", B, moved)
    _git(repo, "commit", "--quiet", "-m", "Move")

    _mark(repo, moved, at=past)

    report = read_report(_settings(repo), repo / REPORT)
    assert report.files == {moved: _git(repo, "rev-parse", f"{past}:{B}")}


def test_files_sharing_a_mark_get_no_yaml_alias(repo: Path) -> None:
    past = _git(repo, "rev-parse", "HEAD")
    _write(repo / "content" / "sec" / "new.md", "# New\n")
    _commit(repo, "New", "content/sec/new.md")
    _mark(repo, "content/sec/new.md", today=date(2030, 1, 1))

    _mark(repo, A, B, at=past)

    text = (repo / REPORT).read_text(encoding="utf8")
    assert "&id" not in text
    assert "*id" not in text
    assert set(read_report(_settings(repo), repo / REPORT).own) == {A, B}
