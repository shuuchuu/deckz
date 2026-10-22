"""Report a scheduled CI run's problems in a GitHub issue: `deckz hooks ci-report`.

The scheduled job (`deckz hooks install --ci`) writes what failed to a
directory: the slow checks' output (`checks.txt`) and the failed builds'
report (`builds.md`, `deckz run decks --report`). This turns them into one
issue whose body a person can paste to an agent: what failed, the command
reproducing each failure, and its errors. GitHub emails it to the people it
mentions and assigns (`ci.report_to`), body included, so the report reaches
them with no mail server or secret to set up. While that issue is open, a
new run's report is a comment on it instead of another issue.

The GitHub API is called with the job's own `GITHUB_TOKEN` (the workflow
grants it `issues: write`), through urllib: the CI image has no `gh`.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .exceptions import DeckzError

LABEL = "deckz-ci"
"""The label of the issue each report goes to, while it's open."""
CHECKS_REPORT = "checks.txt"
BUILDS_REPORT = "builds.md"
_BODY_MAX = 60_000
"""GitHub refuses an issue or comment body over 65,536 characters."""


@dataclass(frozen=True)
class RunContext:
    """Which run the report is about, from the job's environment."""

    repository: str
    """`owner/name`."""
    token: str
    run_url: str
    commit: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "RunContext":
        """Read the variables GitHub Actions sets in every job.

        Returns:
            The run's context.

        Raises:
            DeckzError: If one is missing (not in a GitHub Actions job, or \
                `GITHUB_TOKEN` not passed to the step).
        """
        names = ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "GITHUB_RUN_ID", "GITHUB_SHA")
        if missing := [name for name in names if not environ.get(name)]:
            msg = (
                f"{', '.join(missing)} not set: `deckz hooks ci-report` runs in a"
                " GitHub Actions job, its step given `GITHUB_TOKEN: ${{ github.token"
                " }}` (`deckz hooks install --ci` writes it so)"
            )
            raise DeckzError(msg)
        server = environ.get("GITHUB_SERVER_URL", "https://github.com")
        repository = environ["GITHUB_REPOSITORY"]
        return cls(
            repository=repository,
            token=environ["GITHUB_TOKEN"],
            run_url=f"{server}/{repository}/actions/runs/{environ['GITHUB_RUN_ID']}",
            commit=environ["GITHUB_SHA"],
        )


def report_body(
    reports_dir: Path,
    *,
    checks_command: str,
    run_url: str,
    commit: str,
    report_to: Sequence[str],
) -> str | None:
    """The issue body for the reports in `reports_dir`.

    Args:
        reports_dir: Where the job wrote `checks.txt` and `builds.md`.
        checks_command: The command whose output `checks.txt` holds.
        run_url: The run's page.
        commit: The commit it ran on.
        report_to: GitHub logins to mention.

    Returns:
        The body, or None when no report holds anything.
    """
    sections = []
    checks = reports_dir / CHECKS_REPORT
    if checks.is_file() and (text := checks.read_text(encoding="utf8").strip()):
        sections.append(
            "\n".join(
                [
                    "# Checks that failed",
                    "",
                    f"`{checks_command}` reported these problems, each ending with"
                    " its fix. Run it again to see that they're gone.",
                    "",
                    "```text",
                    text,
                    "```",
                ]
            )
        )
    builds = reports_dir / BUILDS_REPORT
    if builds.is_file() and (text := builds.read_text(encoding="utf8").strip()):
        sections.append(text)
    if not sections:
        return None
    mentions = " ".join(f"@{login}" for login in report_to)
    head = f"The scheduled run {run_url} on {commit[:12]} found what follows." + (
        f" {mentions}" if mentions else ""
    )
    body = "\n\n".join([head, *sections])
    if len(body) > _BODY_MAX:
        body = (
            body[:_BODY_MAX] + f"\n\n[... cut: the run's log has the rest, {run_url}]"
        )
    return body


type Opener = Callable[[Request], Any]


def _call(
    opener: Opener, context: RunContext, method: str, path: str, data: Any = None
) -> Any:
    request = Request(
        f"https://api.github.com/repos/{context.repository}{path}",
        method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {context.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener(request) as response:
        return json.loads(response.read() or b"null")


def _open_issue(
    opener: Opener, context: RunContext, body: str, report_to: Sequence[str]
) -> str:
    """Open the `deckz-ci` issue, assigned to `report_to` when they can be.

    Returns:
        Its URL.

    Raises:
        HTTPError: If GitHub refuses it.
    """
    issue = {
        "title": "deckz: the scheduled checks or builds found problems",
        "body": body,
        "labels": [LABEL],
        "assignees": list(report_to),
    }
    try:
        return _call(opener, context, "POST", "/issues", issue)["html_url"]
    except HTTPError as error:
        if error.code != 422 or not report_to:
            raise
    # A login that can't be assigned (no access): mentioned all the same.
    created = _call(opener, context, "POST", "/issues", issue | {"assignees": []})
    return created["html_url"]


def post_report(
    body: str,
    context: RunContext,
    *,
    report_to: Sequence[str],
    opener: Opener = urlopen,
) -> str:
    """Comment `body` on the open `deckz-ci` issue, or open one.

    Args:
        body: The report.
        context: The run, for the repository and the token.
        report_to: GitHub logins to assign a new issue to.
        opener: `urllib.request.urlopen`, which tests replace.

    Returns:
        The issue's or comment's URL.

    Raises:
        DeckzError: If GitHub refuses (the token lacks `issues: write`).
    """
    try:
        found = _call(opener, context, "GET", f"/issues?labels={LABEL}&state=open")
        if not found:
            return _open_issue(opener, context, body, report_to)
        number = found[0]["number"]
        comment = _call(
            opener, context, "POST", f"/issues/{number}/comments", {"body": body}
        )
        return comment["html_url"]
    except HTTPError as error:
        msg = (
            f"GitHub refused the report ({error.code} {error.reason}): the workflow"
            " gives its job `permissions: issues: write` (`deckz hooks install"
            " --ci` writes it so)"
        )
        raise DeckzError(msg) from error
