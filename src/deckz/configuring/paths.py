from pathlib import Path
from typing import Annotated, Any, Self

from appdirs import user_config_dir as appdirs_user_config_dir
from pydantic import AfterValidator, BaseModel, Field, model_validator

from .. import app_name
from ..exceptions import DeckzError
from ..utils import get_git_dir


def _join(base_key: str, to_add: str) -> Path:
    return Field(default_factory=lambda data: data[base_key] / to_add)


_Path = Annotated[Path, AfterValidator(Path.resolve)]


class GlobalPaths(BaseModel):
    current_dir: _Path
    git_dir: _Path = Field(
        default_factory=lambda data: get_git_dir(data["current_dir"])
    )
    settings: _Path = _join("git_dir", "settings.yml")
    shared_dir: _Path = _join("git_dir", "shared")
    figures_dir: _Path = _join("git_dir", "figures")
    shared_img_dir: _Path = _join("shared_dir", "img")
    shared_code_dir: _Path = _join("shared_dir", "code")
    shared_latex_dir: _Path = _join("shared_dir", "latex")
    shared_tikz_pdf_dir: _Path = _join("shared_dir", "tikz")
    shared_plt_pdf_dir: _Path = _join("shared_dir", "plt")
    templates_dir: _Path = _join("git_dir", "templates")
    plt_dir: _Path = _join("figures_dir", "plots")
    tikz_dir: _Path = _join("figures_dir", "tikz")
    yml_templates_dir: _Path = _join("templates_dir", "yml")
    template_global_config: _Path = _join("yml_templates_dir", "global-config.yml")
    template_user_config: _Path = _join("yml_templates_dir", "user-config.yml")
    template_company_config: _Path = _join("yml_templates_dir", "company-config.yml")
    template_deck_config: _Path = _join("yml_templates_dir", "deck-config.yml")
    jinja2_dir: _Path = _join("templates_dir", "jinja2")
    jinja2_main_template: _Path = _join("jinja2_dir", "main.tex")
    jinja2_print_template: _Path = _join("jinja2_dir", "print.tex")
    user_config_dir: _Path = Field(
        default_factory=lambda: Path(appdirs_user_config_dir(app_name))
    )
    global_config: _Path = _join("git_dir", "global-config.yml")
    github_issues: _Path = _join("user_config_dir", "github-issues.yml")
    mails: Path = _join("user_config_dir", "mails.yml")
    gdrive_secrets: _Path = _join("user_config_dir", "gdrive-secrets.json")
    gdrive_credentials: _Path = _join("user_config_dir", "gdrive-credentials.pickle")
    user_config: _Path = _join("user_config_dir", "user-config.yml")

    def model_post_init(self, __context: Any) -> None:
        for field, value in self.__dict__.items():
            setattr(self, field, value.resolve())
        self.user_config_dir.mkdir(parents=True, exist_ok=True)


class Paths(GlobalPaths):
    build_dir: _Path = _join("current_dir", ".build")
    pdf_dir: _Path = _join("current_dir", "pdf")
    local_latex_dir: _Path = _join("current_dir", "latex")
    company_config: _Path = Field(
        default_factory=lambda data: data["git_dir"]
        / data["current_dir"].relative_to(data["git_dir"]).parts[0]
        / "company-config.yml"
    )
    deck_config: _Path = _join("current_dir", "deck-config.yml")
    session_config: _Path = _join("current_dir", "session-config.yml")
    targets: _Path = _join("current_dir", "targets.yml")

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.targets.is_file():
            msg = "Could not find targets. Are you in a deck directory?"
            raise DeckzError(msg)
        return self
