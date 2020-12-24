from logging import getLogger
from typing import Optional

from requests import post
from typer import Argument, launch
from yaml import safe_load as yaml_safe_load

from deckz.cli import app
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths


@app.command()
def issue(title: str, body: Optional[str] = Argument(None), path: str = ".") -> None:
    paths = GlobalPaths(path)
    logger = getLogger(__name__)
    config = yaml_safe_load(paths.github_issues.read_text(encoding="utf8"))
    if not set(["owner", "repo", "api_key"]).issubset(config):
        raise DeckzException(
            "owner, repo or api_key are not present in the github_issues part of your "
            "user config."
        )
    api_key, owner, repo = config["api_key"], config["owner"], config["repo"]
    data = dict(title=title)
    if body is not None:
        data["body"] = body
    response = post(
        f"https://api.github.com/repos/{owner}/{repo}/issues",
        json=data,
        headers=dict(
            Accept="application/vnd.github.v3+json", Authorization=f"token {api_key}",
        ),
    )
    response.raise_for_status()
    json_response = response.json()
    logger.info(f"Created issue at {json_response['html_url']}")
    launch(json_response["html_url"])
