from dataclasses import dataclass
from itertools import chain
from logging import getLogger
from pathlib import Path
from typing import Container, Dict, Iterator, Type, TypeVar

from appdirs import user_config_dir as appdirs_user_config_dir

from deckz import app_name
from deckz.exceptions import DeckzException
from deckz.utils import get_git_dir

_logger = getLogger(__name__)


_GlobalPathsType = TypeVar("_GlobalPathsType", bound="GlobalPaths")


@dataclass
class GlobalPaths:
    current_dir: Path
    git_dir: Path
    settings: Path
    shared_dir: Path
    figures_dir: Path
    shared_img_dir: Path
    shared_code_dir: Path
    shared_latex_dir: Path
    shared_tikz_pdf_dir: Path
    shared_plt_pdf_dir: Path
    templates_dir: Path
    plt_dir: Path
    tikz_dir: Path
    yml_templates_dir: Path
    template_global_config: Path
    template_user_config: Path
    template_company_config: Path
    template_deck_config: Path
    jinja2_dir: Path
    jinja2_main_template: Path
    jinja2_print_template: Path
    user_config_dir: Path
    global_config: Path
    github_issues: Path
    mails: Path
    gdrive_secrets: Path
    gdrive_credentials: Path
    user_config: Path

    def __post_init__(self) -> None:
        for field, value in self.__dict__.items():
            setattr(self, field, Path(value).resolve())
        self.user_config_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _defaults_global_paths(cls, current_dir: Path) -> Dict[str, Path]:
        current_dir = current_dir.resolve()
        git_dir = get_git_dir(current_dir)
        shared_dir = git_dir / "shared"
        templates_dir = git_dir / "templates"
        figures_dir = git_dir / "figures"
        yml_templates_dir = templates_dir / "yml"
        jinja2_dir = templates_dir / "jinja2"
        user_config_dir = Path(appdirs_user_config_dir(app_name))
        return dict(
            current_dir=current_dir,
            git_dir=git_dir,
            shared_dir=shared_dir,
            templates_dir=templates_dir,
            yml_templates_dir=yml_templates_dir,
            jinja2_dir=jinja2_dir,
            user_config_dir=user_config_dir,
            figures_dir=figures_dir,
            plt_dir=figures_dir / "plt",
            shared_plt_pdf_dir=shared_dir / "plt",
            tikz_dir=figures_dir / "tikz",
            shared_tikz_pdf_dir=shared_dir / "tikz",
            settings=git_dir / "settings.yml",
            shared_img_dir=shared_dir / "img",
            shared_code_dir=shared_dir / "code",
            shared_latex_dir=shared_dir / "latex",
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
        cls: Type[_GlobalPathsType],
        current_dir: Path,
        check_depth: bool = True,
        **kwargs: Path,
    ) -> _GlobalPathsType:
        return cls(**{**cls._defaults_global_paths(current_dir), **kwargs})

    def decks_paths(self) -> Iterator["Paths"]:
        for targets_path in self.current_dir.rglob("targets.yml"):
            yield Paths.from_defaults(targets_path.parent)

    def latex_dirs(self) -> Iterator[Path]:
        return chain(
            [self.shared_latex_dir],
            (paths.local_latex_dir for paths in self.decks_paths()),
        )

    def section_files(self) -> Iterator[Path]:
        for latex_dir in self.latex_dirs():
            yield from latex_dir.rglob("*.yml")


_PathsType = TypeVar("_PathsType", bound="Paths")


@dataclass
class Paths(GlobalPaths):
    build_dir: Path
    pdf_dir: Path
    local_latex_dir: Path
    company_config: Path
    deck_config: Path
    session_config: Path
    targets: Path

    @classmethod
    def _defaults_paths(
        cls, current_dir: Path, check_depth: bool, skip: Container[str]
    ) -> Dict[str, Path]:
        defaults = super()._defaults_global_paths(current_dir)
        if check_depth and not defaults["current_dir"].relative_to(
            defaults["git_dir"]
        ).match("*/*"):
            raise DeckzException(
                f"Not deep enough from root {defaults['git_dir']}. "
                "Please follow the directory hierarchy root > company > deck and "
                "invoke this tool from the deck directory."
            )
        additional_defaults_items = dict(
            build_dir=lambda: defaults["current_dir"] / ".build",
            pdf_dir=lambda: defaults["current_dir"] / "pdf",
            local_latex_dir=lambda: defaults["current_dir"] / "latex",
            company_config=lambda: (
                defaults["git_dir"]
                / defaults["current_dir"].relative_to(defaults["git_dir"]).parts[0]
                / "company-config.yml"
            ),
            deck_config=lambda: defaults["current_dir"] / "deck-config.yml",
            session_config=lambda: defaults["current_dir"] / "session-config.yml",
            targets=lambda: defaults["current_dir"] / "targets.yml",
        )
        additional_defaults = {
            key: value_function()
            for key, value_function in additional_defaults_items.items()
            if key not in skip
        }
        return {**defaults, **additional_defaults}

    @classmethod
    def from_defaults(
        cls: Type[_PathsType],
        current_dir: Path,
        check_depth: bool = True,
        **kwargs: Path,
    ) -> _PathsType:
        return cls(
            **{
                **cls._defaults_paths(
                    current_dir,
                    check_depth=check_depth,
                    skip=kwargs,
                ),
                **kwargs,
            }
        )
