from collections.abc import Iterable
from pathlib import Path
from subprocess import run

from ..models import CompileResult
from .protocols import CompilerProtocol


class Compiler(CompilerProtocol):
    def __init__(self, build_command: Iterable[str]) -> None:
        self._build_command = build_command

    def compile(self, file: Path) -> CompileResult:
        completed_process = run(
            [*self._build_command, file.name],
            cwd=file.parent,
            capture_output=True,
            encoding="utf8",
        )
        return CompileResult(
            completed_process.returncode == 0,
            completed_process.stdout,
            completed_process.stderr,
        )
