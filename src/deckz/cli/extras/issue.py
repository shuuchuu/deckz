from pathlib import Path

from .. import app


@app.command()
def issue(
    title: str,
    body: str | None = None,
    /,
    *,
    workdir: Path = Path(),
) -> None:
    """Create an issue on GitHub.

    Args:
        title: Title of the issue to create
        body: Optional body of the issue to create
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...configuring.settings import GlobalSettings
    from ...extras.github_querying import GitHubAPI, IssuesConfig

    logger = getLogger(__name__)

    config = IssuesConfig.from_yaml(
        GlobalSettings.from_yaml(workdir).paths.github_issues
    )
    api = GitHubAPI(config.api_key)
    url = api.create_issue(config.owner, config.repo, title, body, config.project)
    logger.info(
        f"Successfully created the issue [link={url}]on GitHub[/link]",
        extra={"markup": True},
    )
