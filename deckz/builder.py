from collections import defaultdict
from contextlib import ExitStack, redirect_stdout
from enum import Enum
from logging import getLogger
from multiprocessing import Pool
from pathlib import Path
from shutil import copyfile
from subprocess import run
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Tuple

from attr import attrib, attrs
from PyPDF2 import PdfFileMerger

from deckz.exceptions import DeckzException
from deckz.paths import Paths
from deckz.rendering import Renderer
from deckz.settings import Settings
from deckz.targets import Target, Targets


class CompileType(Enum):
    Handout = "handout"
    Presentation = "presentation"
    Print = "print"
    PrintHandout = "print-handout"


@attrs(auto_attribs=True, frozen=True)
class CompileResult:
    ok: bool
    stdout: Optional[str] = attrib(default="")
    stderr: Optional[str] = attrib(default="")


@attrs(auto_attribs=True, frozen=True)
class CompileItem:
    target: Target
    compile_type: CompileType
    copy_result: bool


class Builder:
    def __init__(
        self,
        latex_config: Dict[str, Any],
        settings: Settings,
        paths: Paths,
        targets: Targets,
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ):
        self._latex_config = latex_config
        self._settings = settings
        self._paths = paths
        self._targets = targets
        self._presentation = build_presentation
        self._handout = build_handout
        self._print = build_print
        self._logger = getLogger(__name__)
        self._compile_standalones()
        self._renderer = Renderer(paths)
        self._build_all()

    def _compile_standalones(self) -> None:
        to_compile: List[Tuple[Path, Path]] = []
        compile_results = []
        self._logger.info("Processing standalones")
        for standalone_dir in self._settings.compile_standalones:
            root = self._paths.settings.parent / standalone_dir
            to_compile.extend((root, latex) for latex in root.glob("**/*.py"))
            to_compile.extend((root, latex) for latex in root.glob("**/*.tex"))
        with Pool() as pool:
            compile_results = pool.starmap(self._compile_standalone, to_compile)
        for (_, latex_file), compile_result in zip(to_compile, compile_results):
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

    def _compile_standalone(self, root: Path, input_file: Path) -> CompileResult:
        pdf = (root / "pdf" / input_file.relative_to(root)).with_suffix(".pdf")
        if pdf.exists() and pdf.stat().st_mtime > input_file.stat().st_mtime:
            return CompileResult(True)
        with TemporaryDirectory() as build_dir:
            build_path = Path(build_dir)
            build_file = (build_path / input_file.relative_to(root)).with_suffix(".tex")
            if input_file.suffix == ".py":
                self._generate_latex(input_file, build_file)
            elif input_file.suffix == ".tex":
                self._copy_file(input_file, build_file)
            else:
                raise ValueError(
                    f"Unsupported standalone file extension {input_file.suffix}"
                )
            compile_result = self._compile(build_file)
            if compile_result.ok:
                pdf.parent.mkdir(parents=True, exist_ok=True)
                copyfile(build_file.with_suffix(".pdf"), pdf)
        return compile_result

    def _list_items(self) -> List[CompileItem]:
        to_compile = []
        for target in self._targets:
            if self._presentation:
                to_compile.append(CompileItem(target, CompileType.Presentation, True))
            if self._handout:
                to_compile.append(CompileItem(target, CompileType.Handout, True))
            if self._print:
                to_compile.append(CompileItem(target, CompileType.PrintHandout, False))
        to_compile.sort(key=lambda item: (item.target.name, item.compile_type.value))
        return to_compile

    def _aggregate_compilation_results_by_type(
        self, compile_results: List[CompileResult], items: List[CompileItem]
    ) -> Dict[CompileType, bool]:
        result: Dict[CompileType, bool] = defaultdict(lambda: True)
        for compile_result, item in zip(compile_results, items):
            result[item.compile_type] &= compile_result.ok
        return result

    def _build_all(self) -> None:
        items = self._list_items()
        n_outputs = (
            int(self._handout) * (len(self._targets) + 1)
            + int(self._presentation) * len(self._targets)
            + int(self._print)
        )
        self._logger.info(f"Building {len(items)} PDFs used in {n_outputs} outputs")
        with Pool() as pool:
            compile_results = pool.map(self._build, items)
        ok_by_type = self._aggregate_compilation_results_by_type(compile_results, items)
        if self._print:
            if ok_by_type[CompileType.PrintHandout]:
                self._logger.info(
                    f"Formatting {len(self._targets)} PDFs into a printable output"
                )
                compile_results.append(
                    self._build(CompileItem(None, CompileType.Print, True))
                )
            else:
                self._logger.warning(
                    "Preparatory compilations failed. Skipping print output"
                )
        if self._handout:
            if ok_by_type[CompileType.Handout]:
                self._logger.info(
                    f"Formatting {len(self._targets)} PDFs into a handout"
                )
                self._merge_pdfs(CompileType.Handout, True)
            else:
                self._logger.warning(
                    "Preparatory compilations failed. Skipping handout output"
                )
        for compile_result, item in zip(compile_results, items):
            if item.target is not None:
                compilation = f"{item.target.name}/{item.compile_type.value}"
            else:
                compilation = item.compile_type.value
            if not compile_result.ok:
                self._logger.warning("Compilation %s errored", compilation)
                self._logger.warning(
                    "Captured %s stderr\n%s", compilation, compile_result.stderr
                )
                self._logger.warning(
                    "Captured %s stdout\n%s", compilation, compile_result.stdout
                )

    def _get_filename(self, target: Optional[Target], compile_type: CompileType) -> str:
        name = self._latex_config["deck_acronym"]
        if target is not None:
            name += f"-{target.name}"
        name += f"-{compile_type.value}"
        return name.lower()

    def _merge_pdfs(self, compile_type: CompileType, copy_result: bool = True) -> None:
        build_dir = self._setup_build_dir(None, compile_type)
        filename = self._get_filename(None, compile_type)
        build_pdf_path = build_dir / f"{filename}.pdf"
        output_pdf_path = self._paths.pdf_dir / f"{filename}.pdf"
        input_pdf_paths = [
            (
                self._paths.build_dir
                / target.name
                / CompileType.Handout.value
                / self._get_filename(target, CompileType.Handout)
            ).with_suffix(".pdf")
            for target in self._targets
        ]
        with ExitStack() as stack, build_pdf_path.open("wb") as fh:
            merger = PdfFileMerger()
            input_files = [stack.enter_context(p.open("rb")) for p in input_pdf_paths]
            for input_file in input_files:
                merger.append(input_file)
            merger.write(fh)
        if copy_result:
            self._paths.pdf_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)

    def _build(self, item: CompileItem) -> CompileResult:
        build_dir = self._setup_build_dir(item.target, item.compile_type)
        filename = self._get_filename(item.target, item.compile_type)
        latex_path = build_dir / f"{filename}.tex"
        build_pdf_path = latex_path.with_suffix(".pdf")
        output_pdf_path = self._paths.pdf_dir / f"{filename}.pdf"
        if item.compile_type is CompileType.Print:
            self._write_print_latex(self._targets, latex_path)
        else:
            self._write_main_latex(item.target, item.compile_type, latex_path)
            copied = self._copy_dependencies(item.target, build_dir)
            self._render_dependencies(copied, build_dir)

        compile_result = self._compile(latex_path)
        if item.copy_result and compile_result.ok:
            self._paths.pdf_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)
        return compile_result

    def _setup_build_dir(
        self, target: Optional[Target], compile_type: CompileType
    ) -> Path:
        target_build_dir = self._paths.build_dir
        if target is not None:
            target_build_dir /= target.name
        target_build_dir /= compile_type.value
        target_build_dir.mkdir(parents=True, exist_ok=True)
        for item in [
            self._paths.shared_img_dir,
            self._paths.shared_tikz_dir,
            self._paths.shared_code_dir,
        ]:
            self._setup_link(target_build_dir / item.name, item)
        return target_build_dir

    def _write_main_latex(
        self, target: Target, compile_type: CompileType, output_path: Path
    ) -> None:
        self._renderer.render(
            template_path=self._paths.jinja2_main_template,
            output_path=output_path,
            config=self._latex_config,
            target=target,
            handout=compile_type in [CompileType.Handout, CompileType.PrintHandout],
            print=compile_type is CompileType.PrintHandout,
        )

    def _write_print_latex(self, targets: Targets, output_path: Path) -> None:
        self._renderer.render(
            template_path=self._paths.jinja2_print_template,
            output_path=output_path,
            pdf_paths=[
                "../%s/%s/%s"
                % (
                    target.name,
                    CompileType.PrintHandout.value,
                    self._get_filename(target, CompileType.PrintHandout),
                )
                for target in targets
            ],
            format="1x2",
        )

    def _copy_dependencies(self, target: Target, target_build_dir: Path) -> List[Path]:
        copied = []
        for dependency in target.dependencies.used:
            try:
                link_dir = (
                    target_build_dir
                    / dependency.relative_to(self._paths.shared_dir).parent
                )
            except ValueError:
                link_dir = (
                    target_build_dir
                    / dependency.relative_to(
                        self._paths.current_dir / target.name
                    ).parent
                )
            link_dir.mkdir(parents=True, exist_ok=True)
            destination = (link_dir / dependency.name).with_suffix(".tex.j2")
            if (
                not destination.exists()
                or destination.stat().st_mtime < dependency.stat().st_mtime
            ):
                self._copy_file(dependency, destination)
                copied.append(destination)
        return copied

    def _render_dependencies(
        self, to_render: List[Path], target_build_dir: Path
    ) -> None:
        for item in to_render:
            self._renderer.render(template_path=item, output_path=item.with_suffix(""))

    def _compile(self, latex_path: Path) -> CompileResult:
        command = self._settings.build_command[:]
        command.append(latex_path.name)
        completed_process = run(
            command, cwd=latex_path.parent, capture_output=True, encoding="utf8"
        )
        return CompileResult(
            completed_process.returncode == 0,
            completed_process.stdout,
            completed_process.stderr,
        )

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

    def _copy_file(self, original: Path, copy: Path) -> None:
        if copy.exists() and copy.stat().st_mtime > original.stat().st_mtime:
            return
        else:
            copy.parent.mkdir(parents=True, exist_ok=True)
            copyfile(original, copy)
