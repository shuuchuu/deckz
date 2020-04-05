from logging import getLogger
from pathlib import Path
from typing import Optional

from appdirs import user_config_dir
from pygit2 import discover_repository, Repository

from deckz import app_name


_logger = getLogger(__name__)


class Paths:
    def __init__(self, working_dir: str) -> None:
        self.working_dir = Path(working_dir).resolve()
        self.build_dir = self.working_dir / "build"
        self.pdf_dir = self.working_dir / "pdf"
        self.shared_dir = self.git_dir / "shared"
        self.shared_img_dir = self.shared_dir / "img"
        self.shared_code_dir = self.shared_dir / "code"
        self.shared_latex_dir = self.shared_dir / "latex"
        self.jinja2_dir = self.git_dir / "jinja2"
        self.user_config_dir = Path(user_config_dir(app_name))
        self.global_config = self.git_dir / "global-config.yml"
        self.user_config = self.user_config_dir / "user-config.yml"
        self.company_config = self.working_dir.parent / "company-config.yml"
        self.deck_config = self.working_dir / "deck-config.yml"
        self.session_config = self.working_dir / "session-config.yml"
        self.targets = self.working_dir / "targets.yml"
        self.targets_debug = self.working_dir / "targets-debug.yml"

        self.user_config_dir.mkdir(parents=True, exist_ok=True)

        if not self.working_dir.relative_to(self.git_dir).match("*/*"):
            _logger.critical(
                f"Not deep enough from root {self.git_dir}. "
                "Please follow the directory hierarchy root > company > deck and "
                "invoke this tool from the deck directory."
            )
            exit(1)

    @property
    def git_dir(self) -> Optional[Path]:
        if not hasattr(self, "_git_dir"):
            repository_path = discover_repository(str(self.working_dir))
            if repository_path is None:
                _logger.critical(
                    "Could not find the path of the current git working directory. "
                    "Are you in one?"
                )
                exit(1)
            repository = Repository(repository_path)
            self._git_dir = Path(repository.workdir).resolve()
        return self._git_dir

    def get_jinja2_template_path(self, version: str) -> Path:
        return self.jinja2_dir / f"{version}.tex.jinja2"
