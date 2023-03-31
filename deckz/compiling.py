from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from typing import Optional

from deckz.settings import Settings


@dataclass(frozen=True)
class CompilePaths:
    latex: Path
    build_pdf: Path
    output_pdf: Path
    build_log: Path
    output_log: Path


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    stdout: Optional[str] = ""
    stderr: Optional[str] = ""


def compile(latex_path: Path, settings: Settings) -> CompileResult:
    completed_process = run(
        settings.build_command + [latex_path.name],
        cwd=latex_path.parent,
        capture_output=True,
        encoding="utf8",
    )
    return CompileResult(
        completed_process.returncode == 0,
        completed_process.stdout,
        completed_process.stderr,
    )
