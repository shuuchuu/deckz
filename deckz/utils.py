from pathlib import Path
from shutil import copyfile
from typing import Optional

from git import Repo
from git.exc import InvalidGitRepositoryError

from deckz.exceptions import DeckzException


def get_git_dir(path: Path) -> Optional[Path]:
    try:
        repository = Repo(str(path), search_parent_directories=True)
    except InvalidGitRepositoryError as e:
        raise DeckzException(
            "Could not find the path of the current git working directory. "
            "Are you in one?"
        ) from e
    return Path(repository.git.rev_parse("--show-toplevel")).resolve()


def copy_file_if_newer(original: Path, copy: Path) -> None:
    if copy.exists() and copy.stat().st_mtime > original.stat().st_mtime:
        return
    else:
        copy.parent.mkdir(parents=True, exist_ok=True)
        copyfile(original, copy)
