from enum import Enum
from filecmp import cmp
from itertools import product as itertools_product
from logging import getLogger
from multiprocessing import Pool
from os import unlink
from os.path import join as path_join
from pathlib import Path
from shutil import copyfile, move
from subprocess import CompletedProcess, run
from tempfile import NamedTemporaryFile
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from deckz.exceptions import DeckzException
from deckz.paths import Paths
from deckz.targets import Target, Targets


class CompileType(Enum):
    Handout = "handout"
    Presentation = "presentation"


class Builder:
    def __init__(
        self, config: Dict[str, Any], paths: Paths,
    ):
        self.config = config
        self.paths = paths
        self._logger = getLogger(__name__)

    def build_all(self, targets: Targets, presentation: bool, handout: bool) -> None:
        compile_types = []
        if presentation:
            compile_types.append(CompileType.Presentation)
        if handout:
            compile_types.append(CompileType.Handout)
        self._logger.info(f"Building {len(targets) * len(compile_types)} outputs")
        to_compile = sorted(
            itertools_product(targets, compile_types),
            key=lambda x: (x[0].name, x[1].value),
        )
        with Pool() as pool:
            completed_processes = pool.starmap(self._build, to_compile)
        for completed_process, (target, compile_type) in zip(
            completed_processes, to_compile
        ):
            if completed_process.returncode != 0:
                self._logger.warning(
                    "Compilation %s/%s errored", target.name, compile_type.value
                )
                self._logger.warning(
                    "Captured %s/%s stderr\n%s",
                    target.name,
                    compile_type.value,
                    completed_process.stderr,
                )
                self._logger.warning(
                    "Captured %s/%s stdout\n%s",
                    target.name,
                    compile_type.value,
                    completed_process.stdout,
                )

    def _build(self, target: Target, compile_type: CompileType) -> CompletedProcess:
        target_build_dir = self._setup_build_dir(target, compile_type)
        filename = (
            f"{self.config['deck_acronym']}-{target.name}-{compile_type.value}".lower()
        )
        latex_path = target_build_dir / f"{filename}.tex"
        build_pdf_path = latex_path.with_suffix(".pdf")
        output_pdf_path = self.paths.pdf_dir / f"{filename}.pdf"
        self._write_main_latex(target, compile_type, latex_path)
        self._link_dependencies(target, target_build_dir)

        completed_process = self._compile(
            latex_path=latex_path.relative_to(target_build_dir),
            target_build_dir=target_build_dir,
        )
        if completed_process.returncode == 0:
            self.paths.pdf_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)
        return completed_process

    def _setup_build_dir(self, target: Target, compile_type: CompileType) -> Path:
        target_build_dir = self.paths.build_dir / target.name / compile_type.value
        target_build_dir.mkdir(parents=True, exist_ok=True)
        for item in self.paths.shared_dir.iterdir():
            self._setup_link(target_build_dir / item.name, item)
        return target_build_dir

    def _write_main_latex(
        self, target: Target, compile_type: CompileType, output_path: Path,
    ) -> None:
        env = Environment(
            loader=FileSystemLoader(searchpath=self.paths.jinja2_dir),
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
        env.filters["camelcase"] = self._to_camel_case
        env.filters["path_join"] = lambda paths: path_join(*paths)

        try:
            filename = self.paths.get_jinja2_template_path("v1").name
            template = env.get_template(filename)
        except TemplateNotFound as e:
            raise DeckzException(
                f"Could not find '{filename}' in {self.paths.jinja2_dir}"
            ) from e
        try:
            with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
                fh.write(
                    template.render(
                        config=self.config,
                        target=target,
                        handout=compile_type is CompileType.Handout,
                    )
                )
                fh.write("\n")
            if not output_path.exists() or not cmp(fh.name, str(output_path)):
                move(fh.name, output_path)
        finally:
            try:
                unlink(fh.name)
            except FileNotFoundError:
                pass

    def _link_dependencies(self, target: Target, target_build_dir: Path) -> None:
        for dependency in target.dependencies.shared:
            link_dir = (
                target_build_dir / dependency.relative_to(self.paths.shared_latex_dir)
            ).parent
            link_dir.mkdir(parents=True, exist_ok=True)
            self._setup_link(link_dir / dependency.name, dependency)

        for dependency in target.dependencies.local:
            link_dir = (
                target_build_dir
                / dependency.relative_to(self.paths.working_dir / target.name)
            ).parent
            link_dir.mkdir(parents=True, exist_ok=True)
            self._setup_link(link_dir / dependency.name, dependency)

    def _compile(self, latex_path: Path, target_build_dir: Path) -> CompletedProcess:
        command = [
            "latexmk",
            "-pdflatex=xelatex -shell-escape -interaction=nonstopmode %O %S",
            "-dvi-",
            "-ps-",
            "-pdf",
        ]
        command.append(str(latex_path))
        return run(command, cwd=target_build_dir, capture_output=True, encoding="utf8")

    def _setup_link(self, source: Path, target: Path) -> None:
        if not target.exists():
            raise DeckzException(
                f"{target} could not be found. Please make sure it exists before "
                "proceeding."
            )
        target = target.resolve()
        if source.is_symlink():
            if source.resolve().samefile(target):
                return
            raise DeckzException(
                f"{source} already exists in the build directory and does not point to "
                f"{target}. Please clean the build directory."
            )
        elif source.exists():
            raise DeckzException(
                f"{source} already exists in the build directory. Please clean the "
                "build directory."
            )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.symlink_to(target)

    def _to_camel_case(self, string: str) -> str:
        return "".join(substring.capitalize() or "_" for substring in string.split("_"))
