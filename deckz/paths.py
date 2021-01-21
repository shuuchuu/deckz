from logging import getLogger
from pathlib import Path

from appdirs import user_config_dir

from deckz import app_name
from deckz.exceptions import DeckzException
from deckz.utils import get_git_dir


_logger = getLogger(__name__)


class GlobalPaths:
    def __init__(self, current_dir: str) -> None:
        self.current_dir = Path(current_dir).resolve()
        self.settings = self.git_dir / "settings.yml"
        self.shared_dir = self.git_dir / "shared"
        self.shared_img_dir = self.shared_dir / "img"
        self.shared_code_dir = self.shared_dir / "code"
        self.shared_latex_dir = self.shared_dir / "latex"
        self.shared_tikz_dir = self.shared_dir / "tikz"
        self.templates_dir = self.git_dir / "templates"
        self.yml_templates_dir = self.templates_dir / "yml"
        self.template_targets = self.yml_templates_dir / "targets.yml"
        self.template_global_config = self.yml_templates_dir / "global-config.yml"
        self.template_user_config = self.yml_templates_dir / "user-config.yml"
        self.template_company_config = self.yml_templates_dir / "company-config.yml"
        self.template_deck_config = self.yml_templates_dir / "deck-config.yml"
        self.jinja2_dir = self.templates_dir / "jinja2"
        self.jinja2_main_template = self.jinja2_dir / "main.tex"
        self.jinja2_print_template = self.jinja2_dir / "print.tex"
        self.user_config_dir = Path(user_config_dir(app_name))
        self.global_config = self.git_dir / "global-config.yml"
        self.github_issues = self.user_config_dir / "github-issues.yml"
        self.gdrive_secrets = self.user_config_dir / "gdrive-secrets.json"
        self.gdrive_credentials = self.user_config_dir / "gdrive-credentials.pickle"
        self.user_config = self.user_config_dir / "user-config.yml"

    @property
    def git_dir(self) -> Path:
        if not hasattr(self, "_git_dir"):
            self._git_dir = get_git_dir(self.current_dir)
        return self._git_dir


class Paths(GlobalPaths):
    def __init__(self, current_dir: str) -> None:
        super().__init__(current_dir)

        if not self.current_dir.relative_to(self.git_dir).match("*/*"):
            raise DeckzException(
                f"Not deep enough from root {self.git_dir}. "
                "Please follow the directory hierarchy root > company > deck and "
                "invoke this tool from the deck directory."
            )

        self.build_dir = self.current_dir / "build"
        self.pdf_dir = self.current_dir / "pdf"
        self.company_config = (
            self.git_dir
            / self.current_dir.relative_to(self.git_dir).parts[0]
            / "company-config.yml"
        )
        self.deck_config = self.current_dir / "deck-config.yml"
        self.session_config = self.current_dir / "session-config.yml"
        self.targets = self.current_dir / "targets.yml"

        self.user_config_dir.mkdir(parents=True, exist_ok=True)
