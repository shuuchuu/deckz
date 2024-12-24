from dataclasses import dataclass


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    stdout: str | None = ""
    stderr: str | None = ""
