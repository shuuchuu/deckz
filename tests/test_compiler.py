from pathlib import Path

from pytest import MonkeyPatch

from deckz.components import compiler
from deckz.components.compiler import TypstCompiler


def test_stop_refuses_further_compilations(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Restored after the test: stop() is meant to be final for the process.
    monkeypatch.setattr(compiler, "_stopped", False)
    main = tmp_path / "main.typ"
    main.write_text("Hello\n", encoding="utf8")

    compiler.stop()
    result = TypstCompiler().compile(main)

    assert not result.ok
    assert result.diagnostics == "compilation cancelled"
    assert not main.with_suffix(".pdf").exists()


def test_a_compilation_over_memory_max_fails(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text("Hello\n", encoding="utf8")

    # Any process is over 1 KiB as soon as it exists.
    result = TypstCompiler(memory_max=1024).compile(main)

    assert not result.ok
    assert "went over typst_memory_max" in result.diagnostics


def test_a_compilation_under_memory_max_succeeds(tmp_path: Path) -> None:
    main = tmp_path / "main.typ"
    main.write_text("Hello\n", encoding="utf8")

    result = TypstCompiler(memory_max=8 * 2**30).compile(main)

    assert result.ok
    assert main.with_suffix(".pdf").exists()
