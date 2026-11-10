from pathlib import Path

from . import app


@app.command(name="ci-report")
def ci_report(
    reports: Path, /, *, dry_run: bool = False, workdir: Path = Path()
) -> None:
    """Report what a scheduled CI run found in a GitHub issue.

    For the workflow `deckz hooks install --ci` writes, when its scheduled
    checks, builds or labs fail: REPORTS holds their outputs (`checks.txt`,
    the output of `deckz check --plain` with `ci.nightly_checks`,
    `weekly-checks.txt`, the same with `ci.weekly_checks`, `builds.md`,
    from `deckz run decks --report`, and `labs.txt`, from `deckz labs
    check` on `ci.labs`). It opens an issue labeled
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
    from ...hooks_install import labs_check_command

    ci = GlobalSettings.from_yaml(workdir).ci
    checks_command = "deckz check --plain " + " ".join(ci.nightly_checks)
    weekly_checks_command = "deckz check --plain " + " ".join(ci.weekly_checks)
    labs_command = (
        "" if ci.labs is None else labs_check_command(ci.labs, "<its python>")
    )
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
        labs_command=labs_command,
        weekly_checks_command=weekly_checks_command.strip(),
    )
    if body is None:
        getLogger(__name__).info("No report in %s: nothing to post", reports)
        return
    if context is None:
        print(body)
        return
    print(post_report(body, context, report_to=ci.report_to))
