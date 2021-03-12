from logging import getLogger
from pathlib import Path
from typing import Dict, Type, TypeVar, Union

from appdirs import user_config_dir as appdirs_user_config_dir
from attr import attrib, attrs

from deckz import app_name
from deckz.exceptions import DeckzException
from deckz.utils import get_git_dir


_logger = getLogger(__name__)


def _path_converter(path: Union[str, Path]) -> Path:
    return Path(path).resolve()


_GlobalPathsType = TypeVar("_GlobalPathsType", bound="GlobalPaths")


@attrs(auto_attribs=True)
class GlobalPaths:
    current_dir: Path = attrib(converter=_path_converter)
    git_dir: Path = attrib(converter=_path_converter)
    settings: Path = attrib(converter=_path_converter)
    shared_dir: Path = attrib(converter=_path_converter)
    shared_img_dir: Path = attrib(converter=_path_converter)
    shared_code_dir: Path = attrib(converter=_path_converter)
    shared_latex_dir: Path = attrib(converter=_path_converter)
    shared_tikz_dir: Path = attrib(converter=_path_converter)
    shared_tikz_pdf_dir: Path = attrib(converter=_path_converter)
    templates_dir: Path = attrib(converter=_path_converter)
    yml_templates_dir: Path = attrib(converter=_path_converter)
    template_global_config: Path = attrib(converter=_path_converter)
    template_user_config: Path = attrib(converter=_path_converter)
    template_company_config: Path = attrib(converter=_path_converter)
    template_deck_config: Path = attrib(converter=_path_converter)
    jinja2_dir: Path = attrib(converter=_path_converter)
    jinja2_main_template: Path = attrib(converter=_path_converter)
    jinja2_print_template: Path = attrib(converter=_path_converter)
    user_config_dir: Path = attrib(converter=_path_converter)
    global_config: Path = attrib(converter=_path_converter)
    github_issues: Path = attrib(converter=_path_converter)
    mails: Path = attrib(converter=_path_converter)
    gdrive_secrets: Path = attrib(converter=_path_converter)
    gdrive_credentials: Path = attrib(converter=_path_converter)
    user_config: Path = attrib(converter=_path_converter)

    def __attrs_post_init__(self) -> None:
        self.user_config_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _defaults(current_dir: Path) -> Dict[str, Path]:
        current_dir = current_dir.resolve()
        git_dir = get_git_dir(current_dir)
        shared_dir = git_dir / "shared"
        templates_dir = git_dir / "templates"
        yml_templates_dir = templates_dir / "yml"
        jinja2_dir = templates_dir / "jinja2"
        user_config_dir = Path(appdirs_user_config_dir(app_name))
        shared_tikz_dir = shared_dir / "tikz"
        return dict(
            current_dir=current_dir,
            git_dir=git_dir,
            shared_dir=shared_dir,
            templates_dir=templates_dir,
            yml_templates_dir=yml_templates_dir,
            jinja2_dir=jinja2_dir,
            user_config_dir=user_config_dir,
            shared_tikz_dir=shared_tikz_dir,
            settings=git_dir / "settings.yml",
            shared_img_dir=shared_dir / "img",
            shared_code_dir=shared_dir / "code",
            shared_latex_dir=shared_dir / "latex",
            shared_tikz_pdf_dir=shared_tikz_dir / "pdf",
            template_global_config=yml_templates_dir / "global-config.yml",
            template_user_config=yml_templates_dir / "user-config.yml",
            template_company_config=yml_templates_dir / "company-config.yml",
            template_deck_config=yml_templates_dir / "deck-config.yml",
            jinja2_main_template=jinja2_dir / "main.tex",
            jinja2_print_template=jinja2_dir / "print.tex",
            global_config=git_dir / "global-config.yml",
            github_issues=user_config_dir / "github-issues.yml",
            mails=user_config_dir / "mails.yml",
            gdrive_secrets=user_config_dir / "gdrive-secrets.json",
            gdrive_credentials=user_config_dir / "gdrive-credentials.pickle",
            user_config=user_config_dir / "user-config.yml",
        )

    @classmethod
    def from_defaults(
        cls: Type[_GlobalPathsType], current_dir: Path
    ) -> _GlobalPathsType:
        return cls(**cls._defaults(current_dir))


_PathsType = TypeVar("_PathsType", bound="Paths")


@attrs(auto_attribs=True)
class Paths(GlobalPaths):
    build_dir: Path = attrib(converter=_path_converter)
    pdf_dir: Path = attrib(converter=_path_converter)
    company_config: Path = attrib(converter=_path_converter)
    deck_config: Path = attrib(converter=_path_converter)
    session_config: Path = attrib(converter=_path_converter)
    targets: Path = attrib(converter=_path_converter)

    @classmethod
    def _defaults(cls, current_dir: Path) -> Dict[str, Path]:
        defaults = super()._defaults(current_dir)
        if not defaults["current_dir"].relative_to(defaults["git_dir"]).match("*/*"):
            raise DeckzException(
                f"Not deep enough from root {defaults['git_dir']}. "
                "Please follow the directory hierarchy root > company > deck and "
                "invoke this tool from the deck directory."
            )
        additional_defaults = dict(
            build_dir=defaults["current_dir"] / ".build",
            pdf_dir=defaults["current_dir"] / "pdf",
            company_config=(
                defaults["git_dir"]
                / defaults["current_dir"].relative_to(defaults["git_dir"]).parts[0]
                / "company-config.yml"
            ),
            deck_config=defaults["current_dir"] / "deck-config.yml",
            session_config=defaults["current_dir"] / "session-config.yml",
            targets=defaults["current_dir"] / "targets.yml",
        )
        return {**defaults, **additional_defaults}
