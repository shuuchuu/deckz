from functools import reduce
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from appdirs import user_config_dir as appdirs_user_config_dir
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
)

from .. import app_name
from ..utils import dirs_hierarchy, get_git_dir, load_all_yamls


class LocalizedValues(BaseModel):
    fr: dict[str, str] = Field(default_factory=dict)
    en: dict[str, str] = Field(default_factory=dict)
    all: dict[str, str] = Field(default_factory=dict)

    def get_default(self, value: str, lang: str) -> str:
        if lang == "fr" and value in self.fr:
            return self.fr[value]
        if lang == "en" and value in self.en:
            return self.en[value]
        return self.all.get(value, value)


class DefaultImageValues(BaseModel):
    license: LocalizedValues = Field(default_factory=LocalizedValues)
    author: LocalizedValues = Field(default_factory=LocalizedValues)
    title: LocalizedValues = Field(default_factory=LocalizedValues)


def _convert(input_value: str | Path, info: ValidationInfo) -> Path:
    if isinstance(input_value, str):
        return Path(input_value.format(**info.data))
    return input_value


_Path = Annotated[Path, BeforeValidator(_convert), AfterValidator(Path.resolve)]
_user_config_dir = Path(appdirs_user_config_dir(app_name)).resolve()


# ruff: noqa: RUF027
# mypy: ignore-errors
class GlobalPaths(BaseModel):
    model_config = ConfigDict(validate_default=True)
    current_dir: _Path
    user_config_dir: Literal[_user_config_dir] = _user_config_dir
    git_dir: _Path = Field(
        default_factory=lambda data: get_git_dir(data["current_dir"])
    )
    settings: _Path = "{git_dir}/settings.yml"
    shared_dir: _Path = "{git_dir}/shared"
    figures_dir: _Path = "{git_dir}/figures"
    shared_img_dir: _Path = "{shared_dir}/img"
    shared_code_dir: _Path = "{shared_dir}/code"
    shared_latex_dir: _Path = "{shared_dir}/latex"
    shared_tikz_pdf_dir: _Path = "{shared_dir}/tikz"
    shared_plt_pdf_dir: _Path = "{shared_dir}/plt"
    shared_plotly_pdf_dir: _Path = "{shared_dir}/pltly"
    templates_dir: _Path = "{git_dir}/templates"
    plt_dir: _Path = "{figures_dir}/plots"
    plotly_dir: _Path = "{figures_dir}/pltly"
    tikz_dir: _Path = "{figures_dir}/tikz"
    jinja2_dir: _Path = "{templates_dir}/jinja2"
    jinja2_main_template: _Path = "{jinja2_dir}/main.tex"
    github_issues: _Path = "{user_config_dir}/github-issues.yml"
    mails: _Path = "{user_config_dir}/mails.yml"
    gdrive_secrets: _Path = "{user_config_dir}/gdrive-secrets.json"
    gdrive_credentials: _Path = "{user_config_dir}/gdrive-credentials.pickle"

    def model_post_init(self, __context: Any) -> None:
        for field, value in self.__dict__.items():
            setattr(self, field, value.resolve())
        self.user_config_dir.mkdir(parents=True, exist_ok=True)


class DeckPaths(GlobalPaths):
    build_dir: _Path = "{current_dir}/.build"
    pdf_dir: _Path = "{current_dir}/pdf"
    local_latex_dir: _Path = "{current_dir}/latex"
    deck_definition: _Path = "{current_dir}/deck.yml"


class GlobalSettings(BaseModel):
    build_command: tuple[str, ...]
    file_extension: str = ".tex"
    default_img_values: DefaultImageValues = Field(default_factory=DefaultImageValues)
    paths: GlobalPaths = Field(default_factory=GlobalPaths)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        resolved_path = path.resolve()
        git_dir = get_git_dir(resolved_path).resolve()
        content: dict[str, Any] = reduce(
            lambda a, b: {**a, **b},
            load_all_yamls(
                d
                for p in dirs_hierarchy(git_dir, _user_config_dir, resolved_path)
                if (d := p / "deckz.yml").is_file()
            ),
            {},
        )
        if "paths" not in content:
            content["paths"] = {}
        if "current_dir" not in content["paths"]:
            content["paths"]["current_dir"] = path
        return cls.model_validate(content)


class DeckSettings(GlobalSettings):
    paths: DeckPaths = Field(default_factory=DeckPaths)
