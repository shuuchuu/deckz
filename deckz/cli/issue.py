from pathlib import Path

from click import argument

from . import app, option_workdir


@app.command()
@argument("title")
@argument("body", required=False)
@option_workdir
def issue(title: str, body: str | None, workdir: Path) -> None:
    """Create an issue on GitHub with a given TITLE and an optional BODY."""
    from logging import getLogger

    from ..github_querying import GitHubAPI, IssuesConfig
    from ..paths import GlobalPaths

    logger = getLogger(__name__)
    config = IssuesConfig.from_global_paths(GlobalPaths.from_defaults(workdir))
    api = GitHubAPI(config.api_key)
    url = api.create_issue(config.owner, config.repo, title, body, config.project)
    logger.info(
        f"Successfully created the issue [link={url}]on GitHub[/link]",
        extra=dict(markup=True),
    )
