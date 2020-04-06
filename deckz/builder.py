from filecmp import cmp
from logging import getLogger
from os import unlink
from os.path import join as path_join
from pathlib import Path
from shutil import copyfile, move
from subprocess import CalledProcessError, run
from sys import exit
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from deckz.paths import Paths
from deckz.targets import Target


_logger = getLogger(__name__)


def build(
    config: Dict[str, Any],
    target: Target,
    handout: bool,
    verbose_latexmk: bool,
    paths: Paths,
) -> None:
    filename = f"{config['deck_acronym']}-{target.name}".lower()
    if handout:
        filename += "-handout"
    latex_path = paths.build_dir / f"{filename}.tex"
    build_pdf_path = latex_path.with_suffix(".pdf")
    output_pdf_path = paths.pdf_dir / f"{filename}.pdf"
    _setup_build_dir(paths)
    _write_main_latex(config, target, handout, latex_path, paths)
    _link_includes(
        [link for section in target.sections for link in section.includes],
        target.name,
        paths,
    )

    return_ok = _compile(
        latex_path.relative_to(paths.build_dir),
        verbose_latexmk=verbose_latexmk,
        paths=paths,
    )
    if not return_ok:
        _logger.critical(f"latexmk errored for {build_pdf_path}.")
        exit(1)
    else:
        paths.pdf_dir.mkdir(parents=True, exist_ok=True)
        copyfile(build_pdf_path, output_pdf_path)


def _setup_build_dir(paths: Paths) -> None:
    paths.build_dir.mkdir(parents=True, exist_ok=True)
    for item in paths.shared_dir.iterdir():
        _setup_link(paths.build_dir / item.name, item)


def _write_main_latex(
    config: Dict[str, Any],
    target: Target,
    handout: bool,
    output_path: Path,
    paths: Paths,
) -> None:
    env = Environment(
        loader=FileSystemLoader(searchpath=paths.jinja2_dir),
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
    env.filters["path_join"] = lambda paths: path_join(*paths)

    try:
        filename = paths.get_jinja2_template_path("v1").name
        template = env.get_template(filename)
    except TemplateNotFound:
        _logger.critical(f"Could not find '{filename}' in {paths.jinja2_dir}")
        exit(1)
    try:
        with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
            fh.write(template.render(config=config, target=target, handout=handout))
            fh.write("\n")
        if not output_path.exists() or not cmp(fh.name, str(output_path)):
            move(fh.name, output_path)
    finally:
        try:
            unlink(fh.name)
        except FileNotFoundError:
            pass


def _link_includes(includes: List[str], target_name: str, paths: Paths) -> None:
    for include in includes:
        name = f"{include}.tex"
        source = paths.build_dir / target_name / name
        local_target = Path(target_name) / name
        shared_target = paths.shared_latex_dir / name
        if local_target.exists():
            _setup_link(source, local_target)
        else:
            _setup_link(source, shared_target)


def _compile(path: Path, verbose_latexmk: bool, paths: Paths) -> bool:
    try:
        command = [
            "latexmk",
            "-pdflatex=xelatex -shell-escape -interaction=nonstopmode %O %S",
        ]
        if not verbose_latexmk:
            command.append("-silent")
        command.append(str(path))
        run(command, cwd=paths.build_dir, check=True)
        return True
    except CalledProcessError:
        return False


def _setup_link(source: Path, target: Path) -> None:
    if not target.exists():
        _logger.critical(
            f"{target} could not be found. Please make sure it exists before "
            "proceeding."
        )
        exit(1)
    target = target.resolve()
    if source.is_symlink():
        if source.resolve().samefile(target):
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


def _to_camel_case(string: str) -> str:
    return "".join(substring.capitalize() or "_" for substring in string.split("_"))
