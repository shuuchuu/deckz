import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from functools import partial
from itertools import chain
from logging import getLogger
from multiprocessing import Pool
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ..building.compiling import compile as compiling_compile
from ..exceptions import DeckzError
from ..utils import copy_file_if_newer, import_module_and_submodules

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings


@dataclass(frozen=True)
class CompilePaths:
    latex: Path
    build_pdf: Path
    output_pdf: Path
    build_log: Path
    output_log: Path


class Assets:
    def __init__(self, settings: "GlobalSettings"):
        self.plt_builder = PltBuilder(settings)
        self.tikz_builder = TikzBuilder(settings)

    def build(self) -> None:
        self.plt_builder.build()
        self.tikz_builder.build()


_plt_registry: list[tuple[Path, Path, Callable[[], None]]] = []


def _clear_register() -> None:
    _plt_registry.clear()


def register_plot(
    name: str | None = None,
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def worker(f: Callable[[], None]) -> Callable[[], None]:
        _, *submodules, _ = f.__module__.split(".")
        name = f.__name__.replace("_", "-")
        output_path = (
            Path("/".join(s.replace("_", "-") for s in submodules)) / name
        ).with_suffix(".pdf")
        python_path_str = sys.modules[f.__module__].__file__
        # I don't get why this is needed for mypy. It seems from the definition of
        # ModuleType that __file__ is always a str and never None
        assert python_path_str is not None
        python_path = Path(python_path_str)
        _plt_registry.append((output_path, python_path, f))
        return f

    return worker


class PltBuilder:
    def __init__(self, settings: "GlobalSettings"):
        self._settings = settings
        self._logger = getLogger(__name__)

    def build(self) -> None:
        import matplotlib

        matplotlib.use("PDF")

        sys.dont_write_bytecode = True
        _clear_register()
        try:
            import_module_and_submodules("plots")
        except ModuleNotFoundError:
            self._logger.warning("Could not find plots module, will not produce plots.")
        full_items = [
            (self._settings.paths.shared_plt_pdf_dir / o, p, f)
            for o, p, f in _plt_registry
        ]
        to_build = [(o, p, f) for o, p, f in full_items if self._needs_compile(p, o)]

        if not to_build:
            return

        self._logger.info(f"Processing {len(to_build)} plot(s) that need recompiling")

        for output_path, python_path, function in to_build:
            self._build_pdf(python_path, output_path, function)

    def _build_pdf(
        self, python_path: Path, output_path: Path, function: Callable[[], None]
    ) -> None:
        import matplotlib.pyplot as plt

        output_path.parent.mkdir(parents=True, exist_ok=True)
        function()

        plt.savefig(output_path, bbox_inches="tight")
        plt.close()

    def _needs_compile(self, python_path: Path, output_path: Path) -> bool:
        return (
            not output_path.exists()
            or output_path.stat().st_mtime_ns < python_path.stat().st_mtime_ns
        )


class TikzBuilder:
    def __init__(self, settings: "GlobalSettings"):
        self._settings = settings
        self._logger = getLogger(__name__)

    def build(self) -> None:
        with TemporaryDirectory() as build_dir:
            build_path = Path(build_dir)
            items = [
                (input_path, paths)
                for input_path in chain(
                    self._settings.paths.tikz_dir.rglob("*.py"),
                    self._settings.paths.tikz_dir.rglob("*.tex"),
                )
                if self._needs_compile(
                    input_path,
                    paths := self._compute_compile_paths(input_path, build_path),
                )
            ]

            if not items:
                return

            self._logger.info(f"Processing {len(items)} tikz(s) that need recompiling")

            for item in items:
                self._prepare(*item)

            with Pool() as pool:
                results = pool.map(
                    partial(
                        compiling_compile, build_command=self._settings.build_command
                    ),
                    (item_path.latex for _, item_path in items),
                )

            for (_, paths), result in zip(items, results, strict=True):
                if result.ok:
                    paths.output_pdf.parent.mkdir(parents=True, exist_ok=True)
                    copyfile(paths.build_pdf, paths.output_pdf)
                    paths.output_log.unlink(missing_ok=True)
                elif paths.build_log.exists():
                    paths.output_pdf.parent.mkdir(parents=True, exist_ok=True)
                    copyfile(paths.build_log, paths.output_log)

        failed = []
        for (input_path, paths), result in zip(items, results, strict=True):
            if not result.ok:
                failed.append((input_path, paths.output_log))
                self._logger.warning("Standalone compilation of %s errored", input_path)
                self._logger.warning("Captured stderr\n%s", result.stderr)
        if failed:

            def linkify(path: Path) -> str:
                return f"[link=file://{path}]log[/link]"

            formatted_fails = "\n".join(
                (
                    f"- {file_path.relative_to(self._settings.paths.shared_dir)}"
                    f' ({linkify(log_path) if log_path.exists() else "no log"})'
                )
                for file_path, log_path in failed
            )
            msg = (
                f"standalone compilation errored for {len(failed)} files:\n"
                f"{formatted_fails}\n"
                "Please also check the errors above."
            )
            raise DeckzError(msg)

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
        with output_file.open("w", encoding="utf8") as fh, redirect_stdout(fh):
            exec(compiled)

    def _compute_compile_paths(self, input_file: Path, build_dir: Path) -> CompilePaths:
        latex = (
            build_dir / input_file.relative_to(self._settings.paths.tikz_dir)
        ).with_suffix(".tex")
        build_pdf = latex.with_suffix(".pdf")
        output_pdf = (
            self._settings.paths.shared_tikz_pdf_dir
            / input_file.relative_to(self._settings.paths.tikz_dir)
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
        dirs_to_link = [
            d for d in self._settings.paths.shared_dir.iterdir() if d.is_dir()
        ]
        for d in dirs_to_link:
            build_d = build_dir / d.name
            if not build_d.exists():
                build_d.symlink_to(d)

        if input_file.suffix == ".py":
            self._generate_latex(input_file, compile_paths.latex)
        elif input_file.suffix == ".tex":
            copy_file_if_newer(input_file, compile_paths.latex)
        else:
            msg = f"unsupported standalone file extension {input_file.suffix}"
            raise ValueError(msg)
