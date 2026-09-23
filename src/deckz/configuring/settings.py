from functools import reduce
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

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
from ..utils import dirs_hierarchy, get_git_dir, load_all_yamls


def _convert(input_value: str | Path, info: ValidationInfo) -> Path:
    if isinstance(input_value, str):
        return Path(input_value.format(**info.data))
    return input_value


_Path = Annotated[Path, BeforeValidator(_convert), AfterValidator(Path.resolve)]
_user_config_dir = Path(appdirs_user_config_dir(app_name)).resolve()


# ruff: file-ignore[missing-f-string-syntax]
class GlobalPaths(BaseModel):
    model_config = ConfigDict(validate_default=True)
    current_dir: _Path
    user_config_dir: Path = _user_config_dir
    git_dir: _Path = Field(
        default_factory=lambda data: get_git_dir(data["current_dir"])
    )
    settings: _Path = cast("Path", "{git_dir}/settings.yml")
    assets_dir: _Path = cast("Path", "{git_dir}/assets")
    latex_dir: _Path = cast("Path", "{git_dir}/latex")
    templates_dir: _Path = cast("Path", "{git_dir}/templates")
    jinja2_dir: _Path = cast("Path", "{templates_dir}/jinja2")
    jinja2_main_template: _Path = cast("Path", "{jinja2_dir}/main.tex")
    jinja2_env_module: _Path = cast("Path", "{jinja2_dir}/env.py")
    assets_builders_module: _Path = cast("Path", "{templates_dir}/assets_builders.py")
    github_issues: _Path = cast("Path", "{user_config_dir}/github-issues.yml")
    mails: _Path = cast("Path", "{user_config_dir}/mails.yml")
    gdrive_secrets: _Path = cast("Path", "{user_config_dir}/gdrive-secrets.json")
    gdrive_credentials: _Path = cast(
        "Path", "{user_config_dir}/gdrive-credentials.pickle"
    )

    def model_post_init(self, __context: Any) -> None:
        for field, value in self.__dict__.items():
            setattr(self, field, value.resolve())
        self.user_config_dir.mkdir(parents=True, exist_ok=True)


class DeckPaths(GlobalPaths):
    build_dir: _Path = cast("Path", "{current_dir}/.build")
    pdf_dir: _Path = cast("Path", "{current_dir}/pdf")
    local_latex_dir: _Path = cast("Path", "{current_dir}/latex")
    deck_definition: _Path = cast("Path", "{current_dir}/deck.yml")


class GlobalSettings(BaseModel):
    compiler: Literal["command", "typst"] = "command"
    """How the main rendered file is compiled to PDF.

    `"command"` shells out to `build_command` once per compiled item (e.g. \
    `latexmk`). `"typst"` compiles `.typ` main files with the `typst` Python \
    bindings, each in a child process; under `--watch`, one child per PDF \
    stays alive with Typst's incremental cache, which is what makes rebuilds \
    fast. `build_command` is ignored then.
    """
    build_command: tuple[str, ...] = ()
    typst_parallel_compilations: int = Field(default=1, ge=1)
    """How many Typst compilations (one per PDF) may run at once.

    Each one can take a few GB on a large deck, and Typst already uses every \
    core within a single compilation, so more than 1 mostly trades memory for \
    a small speedup.
    """
    pandoc_command: tuple[str, ...] = ()
    file_extensions: tuple[str, ...] = (".tex",)
    paths: GlobalPaths = Field(default_factory=GlobalPaths)

    @model_validator(mode="after")
    def _check_build_command(self) -> Self:
        if self.compiler == "command" and not self.build_command:
            msg = 'build_command is required when compiler is "command"'
            raise ValueError(msg)
        return self

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
