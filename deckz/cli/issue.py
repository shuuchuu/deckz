from logging import getLogger
from pathlib import Path
from typing import Optional

from typer import Argument
from yaml import safe_load as yaml_safe_load

from deckz.cli import app
from deckz.exceptions import DeckzException
from deckz.github_querying import GitHubAPI
from deckz.paths import GlobalPaths


@app.command()
def issue(
    title: str, body: Optional[str] = Argument(None), path: Path = Path(".")
) -> None:
    """Create an issue on GitHub."""
    paths = GlobalPaths.from_defaults(path)
    logger = getLogger(__name__)
    config = yaml_safe_load(paths.github_issues.read_text(encoding="utf8"))
    if not set(["owner", "repo", "api_key"]).issubset(config):
        raise DeckzException(
            "owner, repo or api_key are not present in the github_issues part of your "
            "user config."
        )
    api_key, owner, repo = config["api_key"], config["owner"], config["repo"]
    project_number = config.get("project_number")
    api = GitHubAPI(api_key)
    url = api.create_issue(owner, repo, title, body, project_number)
    logger.info(
        f"Successfully created the issue [link={url}]on GitHub[/link]",
        extra=dict(markup=True),
    )
