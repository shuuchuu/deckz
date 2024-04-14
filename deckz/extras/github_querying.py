from logging import getLogger
from typing import Any

from pydantic import BaseModel
from requests import post
from yaml import safe_load

from ..configuring.paths import GlobalPaths


class IssuesConfig(BaseModel):
    api_key: str
    repo: str
    owner: str
    project: int | None = None

    @classmethod
    def from_global_paths(cls, paths: GlobalPaths) -> "IssuesConfig":
        return cls.model_validate(
            safe_load(paths.github_issues.read_text(encoding="utf8"))
        )


class GitHubAPI:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._logger = getLogger(__name__)

    def _run_query(self, query: str) -> dict[str, Any]:
        response = post(
            "https://api.github.com/graphql",
            json=dict(query=query),
            headers=dict(Authorization=f"token {self._api_key}"),
        )
        response.raise_for_status()
        return response.json()

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str | None,
        project_number: int | None,
    ) -> str:
        self._logger.info("Retrieving repository id")
        repo_id = self.get_repo_id(owner=owner, repo=repo)
        if project_number is not None:
            self._logger.info("Retrieving project id")
            project_id = self.get_project_id(owner=owner, project_number=project_number)
        self._logger.info("Creating issue")
        extras = ""
        if body is not None:
            extras += f'body: "{body}"\n'
        if project_number is not None:
            extras += f'projectIds: ["{project_id}"]\n'
        response = self._run_query(
            f"""
            mutation {{
              createIssue(input: {{
                repositoryId: "{repo_id}"
                title: "{title}"
                {extras}
              }})
              {{
                issue {{
                  url
                }}
              }}
            }}
            """
        )
        return response["data"]["createIssue"]["issue"]["url"]

    def get_repo_id(self, owner: str, repo: str) -> str:
        response = self._run_query(
            f"""
            {{
              repository(name: "{repo}", owner: "{owner}") {{
                id
              }}
            }}
            """
        )
        return response["data"]["repository"]["id"]

    def get_project_id(self, owner: str, project_number: int) -> str:
        response = self._run_query(
            f"""
            {{
              repositoryOwner(login: "{owner}") {{
                ... on User {{
                  project(number: {project_number}) {{
                    id
                  }}
                }}
                ... on Organization {{
                  project(number: {project_number}) {{
                    id
                  }}
                }}
              }}
            }}
            """
        )
        return response["data"]["repositoryOwner"]["project"]["id"]
