from contextlib import redirect_stdout
from logging import getLogger
from multiprocessing import Pool
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import List

from ray import get as ray_get

from deckz.compiling import compile as compiling_compile, CompileResult
from deckz.paths import GlobalPaths
from deckz.settings import Settings
from deckz.utils import copy_file_if_newer


class StandalonesBuilder:
    def __init__(self, settings: Settings, paths: GlobalPaths):
        self._paths = paths
        self._settings = settings
        self._logger = getLogger(__name__)

    def build(self) -> None:
        self._logger.info("Processing standalones")
        to_compile: List[Path] = []
        compile_results = []
        to_compile.extend(self._paths.shared_tikz_dir.glob("**/*.py"))
        to_compile.extend(self._paths.shared_tikz_dir.glob("**/*.tex"))
        with Pool() as pool:
            compile_results = pool.map(self._compile_standalone, to_compile)
        for latex_file, compile_result in zip(to_compile, compile_results):
            if not compile_result.ok:
                self._logger.warning("Standalone compilation of %s errored", latex_file)
                self._logger.warning("Captured stderr\n%s", compile_result.stderr)

    def _generate_latex(self, python_file: Path, output_file: Path) -> None:
        compiled = compile(
            source=python_file.read_text(encoding="utf8"),
            filename=python_file.name,
            mode="exec",
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf8") as fh:
            with redirect_stdout(fh):
                exec(compiled)

    def _compile_standalone(self, input_file: Path) -> CompileResult:
        pdf = (
            self._paths.shared_tikz_pdf_dir
            / input_file.relative_to(self._paths.shared_tikz_dir)
        ).with_suffix(".pdf")
        if pdf.exists() and pdf.stat().st_mtime > input_file.stat().st_mtime:
            return CompileResult(True)
        with TemporaryDirectory() as build_dir:
            build_path = Path(build_dir)
            build_file = (
                build_path / input_file.relative_to(self._paths.shared_tikz_dir)
            ).with_suffix(".tex")
            if input_file.suffix == ".py":
                self._generate_latex(input_file, build_file)
            elif input_file.suffix == ".tex":
                copy_file_if_newer(input_file, build_file)
            else:
                raise ValueError(
                    f"Unsupported standalone file extension {input_file.suffix}"
                )
            compile_result = ray_get(
                compiling_compile.remote(build_file, self._settings)
            )
            if compile_result.ok:
                pdf.parent.mkdir(parents=True, exist_ok=True)
                copyfile(build_file.with_suffix(".pdf"), pdf)
        return compile_result
