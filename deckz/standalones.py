from contextlib import redirect_stdout
from functools import partial
from importlib import invalidate_caches, reload
from importlib.util import module_from_spec, spec_from_file_location
from itertools import chain
from logging import getLogger
from multiprocessing import Pool
from pathlib import Path
from shutil import copyfile, rmtree
from tempfile import TemporaryDirectory
from unittest.mock import patch

import deckz.plot_utils  # noqa: F401
from deckz.compiling import CompilePaths
from deckz.compiling import compile as compiling_compile
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths
from deckz.plot_utils import _create_tailored_save_function
from deckz.settings import Settings
from deckz.utils import copy_file_if_newer


class StandalonesBuilder:
    def __init__(self, settings: Settings, paths: GlobalPaths):
        self.plt_builder = PltBuilder(settings, paths)
        self.tikz_builder = TikzBuilder(settings, paths)

    def build(self) -> None:
        self.plt_builder.build()
        self.tikz_builder.build()


class PltBuilder:
    def __init__(self, settings: Settings, paths: GlobalPaths):
        self._settings = settings
        self._paths = paths
        self._logger = getLogger(__name__)

    def build(self) -> None:
        self._clean_plt_dir()
        to_process = self._paths.shared_plt_dir.rglob("*.py")
        for python_file in to_process:
            with patch(
                "deckz.plot_utils.save",
                new=_create_tailored_save_function(self._paths, python_file),
            ):
                spec = spec_from_file_location("mod", python_file)
                mod = module_from_spec(spec)
                try:
                    reload(mod)
                except Exception:
                    spec.loader.exec_module(mod)  # type: ignore

    def _clean_plt_dir(self) -> None:
        files_to_clean = chain(
            self._paths.shared_plt_dir.rglob("*.pyc"),
            self._paths.shared_plt_dir.rglob("*.pyo"),
        )
        for f in files_to_clean:
            f.unlink()
        for d in self._paths.shared_plt_dir.rglob("__pycache__"):
            rmtree(d)
        invalidate_caches()


class TikzBuilder:
    def __init__(self, settings: Settings, paths: GlobalPaths):
        self._paths = paths
        self._settings = settings
        self._logger = getLogger(__name__)

    def build(self) -> None:
        with TemporaryDirectory() as build_dir:
            build_path = Path(build_dir)
            items = [
                (input_path, paths)
                for input_path in chain(
                    self._paths.shared_tikz_dir.glob("**/*.py"),
                    self._paths.shared_tikz_dir.glob("**/*.tex"),
                )
                if self._needs_compile(
                    input_path,
                    paths := self._compute_compile_paths(input_path, build_path),
                )
            ]

            if not items:
                return

            self._logger.info(f"Processing {len(items)} tikz that need recompiling")

            for item in items:
                self._prepare(*item)

            with Pool() as pool:
                results = pool.map(
                    partial(compiling_compile, settings=self._settings),
                    (item_path.latex for _, item_path in items),
                )

            for (_, paths), result in zip(items, results):
                if result.ok:
                    paths.output_pdf.parent.mkdir(parents=True, exist_ok=True)
                    copyfile(paths.build_pdf, paths.output_pdf)
                    paths.output_log.unlink(missing_ok=True)
                elif paths.build_log.exists():
                    paths.output_pdf.parent.mkdir(parents=True, exist_ok=True)
                    copyfile(paths.build_log, paths.output_log)

        failed = []
        for (input_path, paths), result in zip(items, results):
            if not result.ok:
                failed.append((input_path, paths.output_log))
                self._logger.warning("Standalone compilation of %s errored", input_path)
                self._logger.warning("Captured stderr\n%s", result.stderr)
        if failed:
            formatted_fails = "\n".join(
                "- %s (%s)"
                % (
                    f.relative_to(self._paths.shared_dir),
                    "no log" if not l.exists() else "[link=file://%s]log[/link]" % l,
                )
                for f, l in failed
            )
            raise DeckzException(
                f"Standalone compilation errored for {len(failed)} files:\n"
                f"{formatted_fails}\n"
                "Please also check the errors above."
            )

    def _needs_compile(self, input_file: Path, compile_paths: CompilePaths) -> bool:
        return (
            not compile_paths.output_pdf.exists()
            or compile_paths.output_pdf.stat().st_mtime < input_file.stat().st_mtime
        )

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

    def _compute_compile_paths(self, input_file: Path, build_dir: Path) -> CompilePaths:
        latex = (
            build_dir / input_file.relative_to(self._paths.shared_tikz_dir)
        ).with_suffix(".tex")
        build_pdf = latex.with_suffix(".pdf")
        output_pdf = (
            self._paths.shared_tikz_pdf_dir
            / input_file.relative_to(self._paths.shared_tikz_dir)
        ).with_suffix(".pdf")
        build_log = latex.with_suffix(".log")
        output_log = output_pdf.with_suffix(".log")
        return CompilePaths(
            latex=latex,
            build_pdf=build_pdf,
            output_pdf=output_pdf,
            build_log=build_log,
            output_log=output_log,
        )

    def _prepare(self, input_file: Path, compile_paths: CompilePaths) -> None:
        build_dir = compile_paths.latex.parent
        build_dir.mkdir(parents=True, exist_ok=True)
        build_img_dir = build_dir / self._paths.shared_img_dir.name
        if not build_img_dir.exists():
            build_img_dir.symlink_to(self._paths.shared_img_dir)

        if input_file.suffix == ".py":
            self._generate_latex(input_file, compile_paths.latex)
        elif input_file.suffix == ".tex":
            copy_file_if_newer(input_file, compile_paths.latex)
        else:
            raise ValueError(
                f"Unsupported standalone file extension {input_file.suffix}"
            )
