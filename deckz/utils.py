from pathlib import Path
from shutil import copyfile

from pygit2 import Repository, discover_repository

from deckz.exceptions import DeckzException


def get_git_dir(path: Path) -> Path:
    repository = discover_repository(str(path))
    if repository is None:
        raise DeckzException(
            "Could not find the path of the current git working directory. "
            "Are you in one?"
        )
    return Path(Repository(repository).workdir).resolve()


def copy_file_if_newer(original: Path, copy: Path) -> None:
    if copy.exists() and copy.stat().st_mtime > original.stat().st_mtime:
        return
    else:
        copy.parent.mkdir(parents=True, exist_ok=True)
        copyfile(original, copy)
