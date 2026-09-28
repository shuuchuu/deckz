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
