import subprocess
from datetime import date
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

REPORT = "reviews/sec.md"
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
    other = repo / "reviews" / "deep" / "other.md"
    mark(_settings(repo), other, [repo / A], today=date(2026, 1, 1))
    _write(repo / A, "# A changed\n")
    _mark(repo, A, today=date(2026, 2, 1))

    found = review_status(_settings(repo), [repo / A])

    review = found.targets[0].files[0]
    assert review.state == "fresh"
    assert [m.report for m in review.marks] == [REPORT, "reviews/deep/other.md"]


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
        repo / "reviews" / "bad.md",
        "---\nreviewed:\n  date: soon\n  base: abc\n  files:\n    x.md: 12\n---\n",
    )
    _write(repo / "reviews" / "unclosed.md", "---\nreviewed: {}\n")
    _write(repo / "reviews" / "fine.md", "# No front matter: nothing recorded\n")

    problems = header_problems(_settings(repo), None)

    assert len(problems) == 2
    bad = next(p for p in problems if p.startswith("reviews/bad.md"))
    assert "`reviewed.date` is not a date" in bad
    assert "`reviewed.base` is not a commit sha" in bad
    assert "x.md is not a blob sha" in bad
    assert any("no closing `---`" in p for p in problems)
    assert header_problems(_settings(repo), [repo / "reviews" / "fine.md"]) == []


def test_the_check_runs_from_deckz_check(repo: Path, capsys: Any) -> None:
    _write(repo / "reviews" / "bad.md", "---\nreviewed: [1]\n---\n")

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
