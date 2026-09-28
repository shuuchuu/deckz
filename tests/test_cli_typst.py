from collections.abc import Callable, Iterator
from contextlib import contextmanager
from logging import DEBUG, WARNING, getLogger
from multiprocessing import active_children
from os import utime
from pathlib import Path
from shutil import copytree
from time import time
from typing import Any

import appdirs
from pygit2 import init_repository
from pypdfium2 import PdfDocument
from pytest import CaptureFixture, fixture, mark, raises

from deckz.cli import main
from deckz.components.compiler import keep_warm
from deckz.components.factory import GlobalSettingsFactory
from deckz.configuring.settings import DeckSettings
from deckz.exceptions import CompilationError
from deckz.pipelines import _run_once, run

_NO_PDF = ("--no-presentation", "--no-print")
_RUN_ARGS = ("run", *_NO_PDF)


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
    pdf = PdfDocument(working_dir / "pdf" / "abc-handout.pdf")
    try:
        return "\n".join(page.get_textpage().get_text_bounded() for page in pdf)
    finally:
        pdf.close()


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


def test_dry_run_plans_without_building(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    main((*_RUN_ARGS, "--dry-run"))

    lines = capsys.readouterr().out.splitlines()
    assert "company/abc/pdf/abc-handout.pdf: render all 2 fragments" in lines[0]
    assert not (working_dir / "pdf").exists()
    assert not (working_dir / ".build").exists()

    main(_RUN_ARGS)
    (working_dir / "content" / "about.md").write_text("# About\n\nNew.\n")
    capsys.readouterr()
    main((*_RUN_ARGS, "--dry-run"))

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "company/abc/pdf/abc-handout.pdf: render 1 of 2 fragments"
    assert lines[1] == "  company/abc/content/about.md"


def test_rebuild_in_same_process_sees_content_edit(working_dir: Path) -> None:
    main(_RUN_ARGS)
    _write_newer(working_dir / "content" / "about.md", "# About\n\nEdited content.\n")

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


_BROKEN_TYPST = "```{=typst}\n#no-such-function()\n```\n"


def _break(path: Path) -> None:
    _write_newer(path, f"# Broken\n\n{_BROKEN_TYPST}")


def test_compile_error_is_reported(working_dir: Path, caplog: Any) -> None:
    _break(working_dir / "content" / "about.md")

    with raises(SystemExit) as exc_info:
        main(_RUN_ARGS)

    assert exc_info.value.code == 1
    assert "Compilation abc-handout errored" in caplog.text
    assert "unknown variable: no-such-function" in caplog.text
    assert not (working_dir / "pdf" / "abc-handout.pdf").exists()


def test_run_decks_fails_on_a_compile_error(working_dir: Path, caplog: Any) -> None:
    _break(working_dir / "content" / "about.md")

    with raises(SystemExit) as exc_info:
        main(("run", "decks", "--handout", "--no-presentation"))

    assert exc_info.value.code == 1
    assert "company/abc failed to compile" in caplog.text


@mark.parametrize(
    ("args", "broken", "message"),
    [
        (
            ("run", "file", "about", "--no-open", *_NO_PDF),
            Path("content/about.md"),
            "about failed to compile",
        ),
        (
            ("run", "section", "greeting", "standard", "--no-open", *_NO_PDF),
            Path("../../content/greeting/hello.md"),
            "greeting@standard failed to compile",
        ),
        (
            ("run", "shared"),
            Path("../../content/greeting/hello.md"),
            "shared failed to compile",
        ),
        (
            ("run", "all"),
            Path("../../content/greeting/hello.md"),
            "run-all failed to compile",
        ),
    ],
)
def test_run_commands_exit_1_on_a_compile_error(
    working_dir: Path,
    caplog: Any,
    args: tuple[str, ...],
    broken: Path,
    message: str,
) -> None:
    _break(working_dir / broken)

    with raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1
    assert message in caplog.text


def test_nothing_to_compile_is_a_warning(working_dir: Path, caplog: Any) -> None:
    main(("run", "shared", "--no-presentation"))

    assert "Nothing to compile" in caplog.text


def test_debug_env_var_keeps_the_exception(working_dir: Path, monkeypatch: Any) -> None:
    _break(working_dir / "content" / "about.md")
    monkeypatch.setenv("DECKZ_DEBUG", "1")

    with raises(CompilationError, match="ABC failed to compile"):
        main(_RUN_ARGS)


def test_debug_flag_keeps_the_exception(working_dir: Path) -> None:
    _break(working_dir / "content" / "about.md")

    with raises(CompilationError, match="ABC failed to compile"):
        main(("--debug", *_RUN_ARGS))


def test_usage_error_exits_2(working_dir: Path) -> None:
    with raises(SystemExit) as exc_info:
        main(("run", "--no-such-option"))

    assert exc_info.value.code == 2


@mark.parametrize(
    ("flag", "level"), [("--quiet", WARNING), ("-v", DEBUG), ("--debug", DEBUG)]
)
def test_verbosity_flags_set_the_log_level(
    working_dir: Path, monkeypatch: Any, flag: str, level: int
) -> None:
    root = getLogger()
    monkeypatch.setattr(root, "level", root.level)

    main((flag, "generate-agent-notes"))

    assert root.level == level


def test_watch_survives_a_compile_error(working_dir: Path, caplog: Any) -> None:
    _break(working_dir / "content" / "about.md")

    _run_once(
        "done",
        run,
        settings=DeckSettings.from_yaml(working_dir),
        lang="fr",
        build_handout=True,
        build_presentation=False,
        build_print=False,
    )

    assert "ABC failed to compile" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_warm_rebuild_sees_content_edit(working_dir: Path) -> None:
    # What `--watch` does: the second build reuses the first's Typst worker
    # processes (and their cache). The edit must still show up.
    with keep_warm():
        main(_RUN_ARGS)
        _write_newer(
            working_dir / "content" / "about.md", "# About\n\nEdited content.\n"
        )
        main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "Edited content." in text
    assert "the answer is 42" not in text


def test_one_shot_build_leaves_no_worker_process(working_dir: Path) -> None:
    # Each compilation's memory must be given back once the build is done.
    main(_RUN_ARGS)

    assert active_children() == []


def test_font_settings_reach_typst(working_dir: Path) -> None:
    git_dir = working_dir.parent.parent
    copytree(Path(__file__).parent / "fonts", git_dir / "fonts")
    main_path = working_dir / "font.typ"
    main_path.write_text('#set text(font: "Noto Sans Lycian")\nHello\n')

    def compile_with_current_settings() -> str:
        settings = DeckSettings.from_yaml(working_dir)
        result = GlobalSettingsFactory(settings).compiler().compile(main_path)
        assert result.ok
        return result.diagnostics

    # The fixture ignores system fonts, where this one may well be installed.
    assert "unknown font family" in compile_with_current_settings()
    with (git_dir / "deckz.yml").open("a", encoding="utf8") as fh:
        # Relative to the git root, not to the deck deckz runs from.
        fh.write("typst_font_paths:\n  - fonts\n")
    assert "unknown font family" not in compile_with_current_settings()


class _RecordingProgress:
    def __init__(self) -> None:
        self.tracked: list[tuple[str, int]] = []
        self.advances = 0

    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        self.tracked.append((description, total))

        def advance() -> None:
            self.advances += 1

        yield advance


def test_build_reports_progress_through_the_reporter(working_dir: Path) -> None:
    progress = _RecordingProgress()

    run(
        settings=DeckSettings.from_yaml(working_dir),
        lang="fr",
        build_handout=True,
        build_presentation=False,
        build_print=False,
        progress=progress,
    )

    # One handout for the whole deck, plus one per part.
    assert progress.tracked == [("Compiling…", 2)]
    assert progress.advances == 2
