from pathlib import Path

from . import app


@app.command(name="ci-report")
def ci_report(
    reports: Path, /, *, dry_run: bool = False, workdir: Path = Path()
) -> None:
    """Report what a scheduled CI run found in a GitHub issue.

    For the workflow `deckz hooks install --ci` writes, when its scheduled
    checks or builds fail: REPORTS holds their outputs (`checks.txt`, the
    output of `deckz check --plain` with `ci.nightly_checks`, and
    `builds.md`, from `deckz run decks --report`). It opens an issue labeled
    `deckz-ci` mentioning and assigning `ci.report_to`, which GitHub emails
    them, body included, or comments on the one still open. The body is
    written to be pasted to an agent: each failure, the command reproducing
    it and its errors.

    Args:
        reports: The directory the scheduled steps wrote their reports to
        dry_run: Print the body instead of posting it (no token needed)
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from os import environ

    from ...ci_report import RunContext, post_report, report_body
    from ...configuring.settings import GlobalSettings

    ci = GlobalSettings.from_yaml(workdir).ci
    checks_command = "deckz check --plain " + " ".join(ci.nightly_checks)
    if dry_run:
        context = None
        run_url, commit = "<run>", environ.get("GITHUB_SHA", "<commit>")
    else:
        context = RunContext.from_environment(environ)
        run_url, commit = context.run_url, context.commit
    body = report_body(
        reports,
        checks_command=checks_command.strip(),
        run_url=run_url,
        commit=commit,
        report_to=ci.report_to,
    )
    if body is None:
        getLogger(__name__).info("No report in %s: nothing to post", reports)
        return
    if context is None:
        print(body)
        return
    print(post_report(body, context, report_to=ci.report_to))
