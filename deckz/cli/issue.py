from logging import getLogger
from pathlib import Path
from typing import Optional

from click import argument
from pydantic import BaseModel
from yaml import safe_load

from deckz.cli import app, option_workdir
from deckz.github_querying import GitHubAPI
from deckz.paths import GlobalPaths


@app.command()
@argument("title")
@argument("body", required=False)
@option_workdir
def issue(title: str, body: Optional[str], workdir: Path) -> None:
    """Create an issue on GitHub with a given TITLE and an optional BODY."""
    logger = getLogger(__name__)
    config = IssuesConfig.from_global_paths(GlobalPaths.from_defaults(workdir))
    api = GitHubAPI(config.api_key)
    url = api.create_issue(config.owner, config.repo, title, body, config.project)
    logger.info(
        f"Successfully created the issue [link={url}]on GitHub[/link]",
        extra=dict(markup=True),
    )


class IssuesConfig(BaseModel):
    api_key: str
    repo: str
    owner: str
    project: Optional[int] = None

    @classmethod
    def from_global_paths(cls, paths: GlobalPaths) -> "IssuesConfig":
        return cls.parse_obj(safe_load(paths.github_issues.read_text(encoding="utf8")))
