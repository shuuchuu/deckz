import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from logging import DEBUG, WARNING, getLogger
from multiprocessing import active_children
from os import environ, killpg, utime
from pathlib import Path
from shutil import copytree
from signal import SIGINT, SIGKILL
from subprocess import PIPE, Popen
from subprocess import run as run_process
from time import sleep, time
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
from deckz.pipelines import OutputKinds, _run_once, run

_NO_PDF = ("--no-presentation", "--no-print")
_RUN_ARGS = ("run", *_NO_PDF)
_HANDOUT_ONLY = OutputKinds(handout=True, presentation=False, print=False)


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


@mark.parametrize(
    ("args", "pdf"),
    [
        (("run", "file", "about", "--no-open"), ".run/file/about/pdf/deck-handout.pdf"),
        (
            ("run", "section", "greeting", "standard", "--no-open"),
            ".run/section/greeting/standard/pdf/deck-handout.pdf",
        ),
        (("run", "decks", "--handout"), "company/abc/pdf/abc-handout.pdf"),
        (("run", "shared", "--handout"), ".run/shared/pdf/shared-handout.pdf"),
        (("run", "all", "--handout"), ".run/all/pdf/run-all-handout.pdf"),
    ],
)
def test_every_run_command_has_a_dry_run(
    working_dir: Path, capsys: CaptureFixture[str], args: tuple[str, ...], pdf: str
) -> None:
    main((*args, "--no-presentation", "--dry-run"))

    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith(f"{pdf}: render all ") for line in lines)
    assert not list(working_dir.parent.parent.glob("**/*.pdf"))


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


def test_failed_sync_run_removes_nothing(working_dir: Path) -> None:
    stale = working_dir / "pdf" / "abc-old.pdf"
    stale.parent.mkdir(exist_ok=True)
    stale.write_bytes(b"%PDF-1.4 stale")
    _break(working_dir / "content" / "about.md")

    with raises(SystemExit):
        main((*_RUN_ARGS, "--sync"))

    assert stale.exists()


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


def test_logs_go_to_stderr(working_dir: Path, tmp_path: Path) -> None:
    # A real process: under pytest, the root logger already has handlers, so
    # main's logging setup is skipped.
    result = run_process(
        [
            sys.executable,
            "-c",
            "from deckz.cli import main; main()",
            *("run", "--no-handout", "--no-presentation", "--no-print"),
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**environ, "XDG_CONFIG_HOME": str(tmp_path / "xdg"), "COLUMNS": "200"},
    )

    assert result.stdout == ""
    assert "Nothing to compile" in result.stderr


def _spawned_children(pid: int) -> list[int]:
    # Every thread's children: deckz spawns its workers from pool threads.
    children = [
        int(child)
        for task in Path(f"/proc/{pid}/task").iterdir()
        for child in (task / "children").read_text().split()
    ]
    spawned = []
    for child in children:
        with suppress(FileNotFoundError):  # Already gone.
            if b"spawn_main" in Path(f"/proc/{child}/cmdline").read_bytes():
                spawned.append(child)
    return spawned


@mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_ctrl_c_stops_the_build_at_once(working_dir: Path, tmp_path: Path) -> None:
    # A compilation that runs for a while, interrupted once its Typst worker
    # is up, the way a terminal does: SIGINT to the whole process group.
    with (working_dir / "content" / "about.md").open("a", encoding="utf8") as fh:
        fh.write("```{=typst}\n#let x = 0\n")
        fh.write("#for i in range(200000000) { x = x + 1 }\n#x\n```\n")
    process = Popen(
        [sys.executable, "-c", "from deckz.cli import main; main()", *_RUN_ARGS],
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        env={**environ, "XDG_CONFIG_HOME": str(tmp_path / "xdg")},
        start_new_session=True,
    )
    try:
        deadline = time() + 20
        while not (workers := _spawned_children(process.pid)):
            assert process.poll() is None, "deckz exited before compiling"
            assert time() < deadline, "no Typst worker started"
            sleep(0.05)

        killpg(process.pid, SIGINT)
        _, stderr = process.communicate(timeout=20)
    finally:
        # Whatever happened, never leave the slow build running.
        with suppress(ProcessLookupError):
            killpg(process.pid, SIGKILL)
        process.wait()

    assert process.returncode == 130
    assert "Interrupted" in stderr
    assert "Traceback" not in stderr
    assert not any(Path(f"/proc/{worker}").exists() for worker in workers)


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
        langs=("fr",),
        outputs=_HANDOUT_ONLY,
    )

    assert "ABC failed to compile" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_warm_rebuild_sees_content_edit(working_dir: Path) -> None:
    # What `--watch` does: the second build reuses the first's Typst worker
    # processes (and their cache). The edit must still show up.
    with keep_warm():
        main(_RUN_ARGS)
        _write_newer(
            working_dir / "content" / "about.md",
            "# About\n\nEdited content.\n\n# Added\n\nA frame.\n",
        )
        main(_RUN_ARGS)

    text = _handout_text(working_dir)
    assert "Edited content." in text
    assert "the answer is 42" not in text
    # The frames it records follow the edits too.
    record = working_dir / ".build" / "abc-handout" / "abc-handout.markers.json"
    assert len(json.loads(record.read_text(encoding="utf8"))["deckz-frame"]) == 3


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
        langs=("fr",),
        outputs=_HANDOUT_ONLY,
        progress=progress,
    )

    # One handout for the whole deck, plus one per part.
    assert progress.tracked == [("Compiling…", 2)]
    assert progress.advances == 2


def test_show_frames_maps_pages_to_content_files(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    main(_RUN_ARGS)
    capsys.readouterr()

    main(("show", "frames", "--json"))

    found = json.loads(capsys.readouterr().out)
    assert [(f["title"], f["file"], f["line"]) for f in found] == [
        ("About", "company/abc/content/about.md", 1),
        ("Hello", "content/greeting/hello.md", 1),
    ]
    assert all(isinstance(f["page"], int) and f["page"] >= 1 for f in found)
    # The marked copies converted in place of the fragments are gone.
    assert not list((working_dir / ".build").rglob(".*.frames.md"))


def test_show_frames_reads_what_the_build_recorded(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    main(_RUN_ARGS)
    build = working_dir / ".build" / "abc-handout"
    record = build / "abc-handout.markers.json"
    recorded = json.loads(record.read_text(encoding="utf8"))
    # Every label deckz reads, even those no marker has.
    assert recorded.keys() == {"deckz-frame", "formation-overflow", "formation-table"}
    markers = recorded["deckz-frame"]
    assert [marker["index"] for marker in markers] == [0, 0]
    # A record is only read while it's as new as the PDF: shift its pages
    # to tell it from a query.
    for marker in markers:
        marker["page"] += 100
    record.write_text(json.dumps(recorded), encoding="utf8")
    capsys.readouterr()

    main(("show", "frames", "--json"))
    assert all(f["page"] > 100 for f in json.loads(capsys.readouterr().out))

    pdf = build / "abc-handout.pdf"
    utime(record, ns=(0, pdf.stat().st_mtime_ns - 1))
    main(("show", "frames", "--json"))
    assert all(f["page"] < 100 for f in json.loads(capsys.readouterr().out))


def test_check_overflow_names_the_shrunk_frame_s_line(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    main(_RUN_ARGS)
    record = working_dir / ".build" / "abc-handout" / "abc-handout.markers.json"
    recorded = json.loads(record.read_text(encoding="utf8"))
    hello = next(
        marker["page"]
        for marker in recorded["deckz-frame"]
        if "greeting" in marker["fragment"]
    )
    # What the theme would record for a frame it shrank.
    recorded["formation-overflow"] = [{"ratio": "90%", "page": hello}]
    record.write_text(json.dumps(recorded), encoding="utf8")
    capsys.readouterr()

    with raises(SystemExit):
        main(("check", "overflow", "--json"))

    assert json.loads(capsys.readouterr().out) == [
        {
            "lang": "fr",
            "ratio": "90%",
            "page": hello,
            "title": "Hello",
            "sources": ["content/greeting/hello.md"],
            "line": 1,
        }
    ]


def test_show_frames_needs_a_build(working_dir: Path) -> None:
    with raises(SystemExit) as exc_info:
        main(("show", "frames"))

    assert exc_info.value.code == 1
