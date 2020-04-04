from filecmp import cmp
from logging import getLogger
from os import unlink
from pathlib import Path
from shutil import copyfile
from subprocess import CalledProcessError, run
from sys import exit
from tempfile import NamedTemporaryFile
from typing import Any, List, Tuple

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from deckz.targets import Section, Target
from deckz.utils import get_workdir_path

_logger = getLogger(__name__)


def _setup_link(source: Path, target: Path) -> None:
    target = target.resolve()
    if not target.exists():
        _logger.critical(
            f"{target} could not be found. Please make sure it exists before "
            "proceeding."
        )
        exit(1)
    if source.is_symlink():
        if source.resolve().samefile(target.resolve()):
            return
        _logger.critical(
            f"{source} already exists in the build directory and does not point to "
            f"{target}. Please clean the build directory."
        )
        exit(1)
    elif source.exists():
        _logger.critical(
            f"{source} already exists in the build directory. Please clean the "
            "build directory."
        )
        exit(1)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.symlink_to(target)


def _setup_build_dir() -> None:

    build_dir = Path("build")
    build_dir.mkdir(exist_ok=True)

    git_dir = get_workdir_path()

    for directory in ["img", "code-illustration", "template"]:
        _setup_link(build_dir / directory, git_dir / directory)


def _to_camel_case(string: str) -> str:
    return "".join(substring.capitalize() or "_" for substring in string.split("_"))


def _write_main_latex(
    config: List[Tuple[str, Any]],
    target_sections: List[Section],
    target_title: str,
    handout: bool,
    output_path: Path,
) -> None:
    git_dir = get_workdir_path()

    env = Environment(
        loader=FileSystemLoader(searchpath=git_dir / "jinja2"),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        line_comment_prefix="%#",
        trim_blocks=True,
        autoescape=False,
    )
    env.filters["camelcase"] = _to_camel_case

    try:
        filename = "deckz_main_template.tex.jinja2"
        template = env.get_template(filename)
    except TemplateNotFound:
        _logger.critical(
            f"Could not find '{filename}' in the jinja2 subdirectory of this git "
            "repository"
        )
        exit(1)
    try:
        with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
            fh.write(
                template.render(
                    config=config,
                    target_title=target_title,
                    handout=handout,
                    sections=target_sections,
                )
            )
            fh.write("\n")
        if not output_path.exists() or not cmp(fh.name, str(output_path)):
            Path(fh.name).replace(output_path)
    finally:
        try:
            unlink(fh.name)
        except FileNotFoundError:
            pass


def _link_includes(includes: List[str]) -> None:
    build_dir = Path("build")
    for include in includes:
        name = f"{include}.tex"
        _setup_link(build_dir / name, Path(name))


def _compile(path: Path, silent_latexmk: bool) -> bool:
    try:
        command = [
            "latexmk",
            "-pdflatex=xelatex -shell-escape -interaction=nonstopmode %O %S",
        ]
        if silent_latexmk:
            command.append("-silent")
        command.append(str(path))
        run(command, cwd="build", check=True)
        return True
    except CalledProcessError:
        return False


def build(
    config: List[Tuple[str, Any]], target: Target, handout: bool, silent_latexmk: bool
) -> None:
    build_dir = Path("build")
    filename = target.name
    if handout:
        filename += "-handout"
    latex_path = build_dir / f"{filename}.tex"
    pdf_path = latex_path.with_suffix(".pdf")
    _setup_build_dir()
    _write_main_latex(config, target.sections, target.title, handout, latex_path)
    _link_includes([link for section in target.sections for link in section.includes])
    return_ok = _compile(
        latex_path.relative_to(build_dir), silent_latexmk=silent_latexmk
    )
    if not return_ok:
        _logger.critical(f"latexmk errored for {pdf_path}.")
        exit(1)
    else:
        copyfile(pdf_path, pdf_path.name)
