from pathlib import Path
from typing import Optional

from typer import Argument
from typing_extensions import Annotated

from .. import WorkdirOption, app


@app.command()
def issue(
    title: str,
    body: Annotated[Optional[str], Argument()] = None,  # noqa: NU002
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """Create an issue on GitHub with a given TITLE and an optional BODY."""
    from logging import getLogger

    from ...configuring.paths import GlobalPaths
    from ...extras.github_querying import GitHubAPI, IssuesConfig

    logger = getLogger(__name__)
    config = IssuesConfig.from_global_paths(GlobalPaths.from_defaults(workdir))
    api = GitHubAPI(config.api_key)
    url = api.create_issue(config.owner, config.repo, title, body, config.project)
    logger.info(
        f"Successfully created the issue [link={url}]on GitHub[/link]",
        extra=dict(markup=True),
    )
