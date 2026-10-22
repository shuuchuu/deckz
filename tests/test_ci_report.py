import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from pytest import raises

from deckz.ci_report import RunContext, post_report, report_body
from deckz.exceptions import DeckzError

CONTEXT = RunContext("owner/repo", "token", "https://github.com/run/1", "abc123" * 7)


def _body(reports: Path, report_to: tuple[str, ...] = ("me",)) -> str | None:
    return report_body(
        reports,
        checks_command="deckz check --plain missing-en",
        run_url=CONTEXT.run_url,
        commit=CONTEXT.commit,
        report_to=report_to,
    )


def test_report_body_holds_the_checks_and_the_builds(tmp_path: Path) -> None:
    (tmp_path / "checks.txt").write_text("missing-en\tcontent/a.md: no en/a.md\n")
    (tmp_path / "builds.md").write_text("# 1 deck build(s) failed\n\n## d, in fr\n")

    body = _body(tmp_path)

    assert body is not None
    assert body.startswith(
        f"The scheduled run {CONTEXT.run_url} on {CONTEXT.commit[:12]} found what"
        " follows. @me\n\n# Checks that failed\n"
    )
    assert "`deckz check --plain missing-en` reported" in body
    assert "content/a.md: no en/a.md" in body
    assert body.endswith("## d, in fr")


def test_report_body_is_none_without_a_report(tmp_path: Path) -> None:
    (tmp_path / "checks.txt").write_text("\n")

    assert _body(tmp_path) is None


class _GitHub:
    """GitHub's issues API, as far as `post_report` uses it."""

    def __init__(self, open_issues: list[dict[str, Any]], refuse: int = 0) -> None:
        self.open_issues = open_issues
        self.refuse = refuse
        """How many POSTs to refuse, the first ones."""
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, request: Request) -> BytesIO:
        data = json.loads(request.data) if request.data else None  # ty: ignore[invalid-argument-type]
        self.calls.append((request.get_method(), request.full_url, data))
        assert request.get_header("Authorization") == "Bearer token"
        if self.refuse and request.get_method() == "POST":
            self.refuse -= 1
            raise HTTPError(request.full_url, 422, "Unprocessable", {}, None)  # ty: ignore[invalid-argument-type]
        if request.get_method() == "GET":
            return BytesIO(json.dumps(self.open_issues).encode())
        return BytesIO(json.dumps({"html_url": "https://github.com/x"}).encode())


def test_post_report_opens_an_issue_assigned_to_report_to() -> None:
    github = _GitHub([])

    post_report("body", CONTEXT, report_to=("me",), opener=github)

    method, url, data = github.calls[-1]
    assert (method, url) == ("POST", "https://api.github.com/repos/owner/repo/issues")
    assert data["labels"] == ["deckz-ci"]
    assert data["assignees"] == ["me"]
    assert data["body"] == "body"


def test_post_report_comments_on_the_open_issue() -> None:
    github = _GitHub([{"number": 7}])

    post_report("body", CONTEXT, report_to=("me",), opener=github)

    assert github.calls[-1][:2] == (
        "POST",
        "https://api.github.com/repos/owner/repo/issues/7/comments",
    )


def test_post_report_opens_it_unassigned_when_assigning_is_refused() -> None:
    github = _GitHub([], refuse=1)

    post_report("body", CONTEXT, report_to=("me",), opener=github)

    assert [call[2]["assignees"] for call in github.calls[1:]] == [["me"], []]


def test_post_report_names_the_permission_when_refused() -> None:
    with raises(DeckzError, match="issues: write"):
        post_report("body", CONTEXT, report_to=(), opener=_GitHub([], refuse=1))


def test_run_context_names_what_is_missing() -> None:
    with raises(DeckzError, match="GITHUB_TOKEN"):
        RunContext.from_environment({"GITHUB_REPOSITORY": "o/r"})
    context = RunContext.from_environment(
        {
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_TOKEN": "t",
            "GITHUB_RUN_ID": "9",
            "GITHUB_SHA": "abc",
        }
    )
    assert context.run_url == "https://github.com/o/r/actions/runs/9"
