from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from subprocess import run


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    stdout: str | None = ""
    stderr: str | None = ""


def compile(latex_path: Path, build_command: Iterable[str]) -> CompileResult:  # noqa: A001
    completed_process = run(
        [*build_command, latex_path.name],
        cwd=latex_path.parent,
        capture_output=True,
        encoding="utf8",
    )
    return CompileResult(
        completed_process.returncode == 0,
        completed_process.stdout,
        completed_process.stderr,
    )
