from os import getcwd
from pathlib import Path
from typing import Optional

from pygit2 import discover_repository, GitError, Repository


def get_workdir_path() -> Optional[Path]:
    cwd = getcwd()
    repository_path = discover_repository(cwd)
    if repository_path is None:
        return None
    try:
        repository = Repository(repository_path)
    except GitError:
        return None
    return Path(repository.workdir)
