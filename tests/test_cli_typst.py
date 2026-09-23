from multiprocessing import active_children
from os import utime
from pathlib import Path
from shutil import copytree
from time import time
from typing import Any

import appdirs
from pdfminer.high_level import extract_text
from pygit2 import init_repository
from pytest import fixture, raises

from deckz.cli import main
from deckz.components.typst_compiler import keep_warm
from deckz.exceptions import DeckzError

_RUN_ARGS = ("run", "--no-presentation", "--no-print")


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / __name__
    tmp_dir = tmp_path / "data"
    tmp_user_dir = tmp_path / "user"
    tmp_user_dir.mkdir()
    copytree(data_dir, tmp_dir)
    init_repository(str(tmp_dir))
    working_dir = tmp_dir / "company" / "abc"
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_user_dir))
    return working_dir


def _handout_text(working_dir: Path) -> str:
    return extract_text(working_dir / "pdf" / "abc-handout.pdf")


def _write_newer(path: Path, content: str) -> None:
    # Guarantees the edit is strictly newer than the build copy made by the
    # previous run, however coarse the filesystem's mtime resolution is.
    path.write_text(content, encoding="utf8")
    future = time() + 10
    utime(path, (future, future))


def test_run_typst(working_dir: Path) -> None:
    main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "Hello from Markdown, the answer is 42!" in text
    assert "Hi there, this shared section is Markdown too!" in text
    assert (working_dir / "pdf" / "abc-p1-handout.pdf").is_file()


def test_rebuild_in_same_process_sees_content_edit(working_dir: Path) -> None:
    main(_RUN_ARGS)
    _write_newer(working_dir / "latex" / "about.md", "# About\n\nEdited content.\n")

    main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "Edited content." in text
    assert "the answer is 42" not in text


def test_filter_change_reconverts_unchanged_fragments(working_dir: Path) -> None:
    main(_RUN_ARGS)
    filter_path = working_dir.parent.parent / "templates" / "pandoc" / "filter.lua"
    filter_path.write_text(
        "function Para(el)\n"
        '  el.content:insert(pandoc.Str(" FILTERED"))\n'
        "  return el\n"
        "end\n",
        encoding="utf8",
    )

    main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "the answer is 42! FILTERED" in text
    assert "Markdown too! FILTERED" in text


def test_compile_error_is_reported(working_dir: Path, caplog: Any) -> None:
    _write_newer(
        working_dir / "latex" / "about.md",
        "# About\n\n```{=typst}\n#no-such-function()\n```\n",
    )

    main(_RUN_ARGS)

    assert "Compilation abc-handout errored" in caplog.text
    assert "unknown variable: no-such-function" in caplog.text
    assert not (working_dir / "pdf" / "abc-handout.pdf").exists()


def test_run_decks_fails_on_a_compile_error(working_dir: Path) -> None:
    _write_newer(
        working_dir / "latex" / "about.md",
        "# About\n\n```{=typst}\n#no-such-function()\n```\n",
    )

    with raises(DeckzError, match="company/abc"):
        main(("run", "decks", "--handout", "--no-presentation"))


def test_warm_rebuild_sees_content_edit(working_dir: Path) -> None:
    # What `--watch` does: the second build reuses the first's Typst worker
    # processes (and their cache). The edit must still show up.
    with keep_warm():
        main(_RUN_ARGS)
        _write_newer(working_dir / "latex" / "about.md", "# About\n\nEdited content.\n")
        main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "Edited content." in text
    assert "the answer is 42" not in text


def test_one_shot_build_leaves_no_worker_process(working_dir: Path) -> None:
    # Each compilation's memory must be given back once the build is done.
    main(_RUN_ARGS)

    assert active_children() == []
