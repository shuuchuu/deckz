from collections.abc import Iterator
from functools import reduce
from pathlib import Path
from typing import Annotated, Any, Self

from appdirs import user_config_dir as appdirs_user_config_dir
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from .. import app_name
from ..exceptions import DeckzError
from ..utils import get_git_dir, intermediate_dirs, load_yaml


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


# ruff: noqa: RUF027
# mypy: ignore-errors
class GlobalPaths(BaseModel):
    model_config = ConfigDict(validate_default=True)
    current_dir: _Path
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
    templates_dir: _Path = "{git_dir}/templates"
    plt_dir: _Path = "{figures_dir}/plots"
    tikz_dir: _Path = "{figures_dir}/tikz"
    yml_templates_dir: _Path = "{templates_dir}/yml"
    template_global_config: _Path = "{yml_templates_dir}/global-config.yml"
    template_user_config: _Path = "{yml_templates_dir}/user-config.yml"
    template_company_config: _Path = "{yml_templates_dir}/company-config.yml"
    template_deck_config: _Path = "{yml_templates_dir}/deck-config.yml"
    jinja2_dir: _Path = "{templates_dir}/jinja2"
    jinja2_main_template: _Path = "{jinja2_dir}/main.tex"
    jinja2_print_template: _Path = "{jinja2_dir}/print.tex"
    user_config_dir: _Path = Field(
        default_factory=lambda: Path(appdirs_user_config_dir(app_name))
    )
    global_config: _Path = "{git_dir}/global-config.yml"
    github_issues: _Path = "{user_config_dir}/github-issues.yml"
    mails: _Path = "{user_config_dir}/mails.yml"
    gdrive_secrets: _Path = "{user_config_dir}/gdrive-secrets.json"
    gdrive_credentials: _Path = "{user_config_dir}/gdrive-credentials.pickle"
    user_config: _Path = "{user_config_dir}/user-config.yml"

    def model_post_init(self, __context: Any) -> None:
        for field, value in self.__dict__.items():
            setattr(self, field, value.resolve())
        self.user_config_dir.mkdir(parents=True, exist_ok=True)


def _company_config_factory(data: dict[str, Any]) -> Path:
    if not data["current_dir"].relative_to(data["git_dir"]).match("*/*"):
        msg = (
            f"not deep enough from root {data['git_dir']}. "
            "Please follow the directory hierarchy root > company > deck and "
            "invoke this tool from the deck directory"
        )
        raise DeckzError(msg)
    return (
        data["git_dir"]
        / data["current_dir"].relative_to(data["git_dir"]).parts[0]
        / "company-config.yml"
    )


class DeckPaths(GlobalPaths):
    build_dir: _Path = "{current_dir}/.build"
    pdf_dir: _Path = "{current_dir}/pdf"
    local_latex_dir: _Path = "{current_dir}/latex"
    company_config: _Path = Field(default_factory=_company_config_factory)
    deck_config: _Path = "{current_dir}/deck-config.yml"
    session_config: _Path = "{current_dir}/session-config.yml"
    targets: _Path = "{current_dir}/targets.yml"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.targets.is_file():
            msg = "Could not find targets. Must be in a deck directory"
            raise ValueError(msg)
        return self


def _load_all_ymls(start: Path, end: Path, name: str) -> Iterator[dict[str, Any]]:
    for path in intermediate_dirs(start, end):
        file = path / name
        if file.is_file():
            yield load_yaml(path / name)


class GlobalSettings(BaseModel):
    build_command: list[str]
    default_img_values: DefaultImageValues = Field(default_factory=DefaultImageValues)
    paths: GlobalPaths = Field(default_factory=GlobalPaths)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        resolved_path = path.resolve()
        git_dir = get_git_dir(resolved_path).resolve()
        if not resolved_path.is_relative_to(git_dir):
            msg = f"{path} is not relative to {git_dir}, cannot load settings"
            raise DeckzError(msg)
        content: dict[str, Any] = reduce(
            lambda a, b: {**a, **b},
            _load_all_ymls(git_dir, resolved_path, "deckz.yml"),
            {},
        )
        if "paths" not in content:
            content["paths"] = {}
        if "current_dir" not in content["paths"]:
            content["paths"]["current_dir"] = path
        return cls.model_validate(content)


class DeckSettings(GlobalSettings):
    paths: DeckPaths = Field(default_factory=DeckPaths)
