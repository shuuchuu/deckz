from pathlib import Path
from subprocess import run
from typing import Optional

from attr import attrib, attrs

from deckz.settings import Settings


@attrs(auto_attribs=True, frozen=True)
class CompileResult:
    ok: bool
    stdout: Optional[str] = attrib(default="")
    stderr: Optional[str] = attrib(default="")


@attrs(auto_attribs=True, frozen=True)
class Compiler:

    _settings: Settings

    def compile(self, latex_path: Path) -> CompileResult:
        completed_process = run(
            self._settings.build_command + [latex_path.name],
            cwd=latex_path.parent,
            capture_output=True,
            encoding="utf8",
        )
        return CompileResult(
            completed_process.returncode == 0,
            completed_process.stdout,
            completed_process.stderr,
        )
