from collections.abc import Iterable
from pathlib import Path
from subprocess import run

from pydantic import BaseModel

from ..models.compilation import CompileResult
from . import Compiler


class DefaultCompilerExtraKwArgs(BaseModel):
    build_command: tuple[str, ...]


class DefaultCompiler(
    Compiler, key="default", extra_kwargs_class=DefaultCompilerExtraKwArgs
):
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
