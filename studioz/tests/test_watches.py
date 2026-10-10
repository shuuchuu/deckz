import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from pytest import fixture
from studioz.watches import State, Watch, Watches

from studioz import watches

# Stands for `deckz run --watch`: the same log lines, the PDF written before
# the build is said finished.
_FAKE_DECKZ = """
import pathlib, signal, sys, time

pdf, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
if mode == "stubborn":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
print("13:00:00 INFO     Building x in fr: handout    _presentation.py:395", flush=True)
print("         INFO     Initial build        pipelines.py:444", flush=True)
if mode == "fail":
    print("13:00:01 ERROR    x: compilation failed     pipelines.py:464", flush=True)
    print("                  error: unknown variable: oops", flush=True)
else:
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4")
    print("Compiling… ━━━━━━━━ 100%", flush=True)
    print("13:00:01 INFO     Initial build finished   pipelines.py:462", flush=True)
try:
    time.sleep(60)
except KeyboardInterrupt:
    pass
"""


@fixture
def deck(tmp_path: Path) -> Path:
    directory = tmp_path / "ws" / "client" / "abc"
    directory.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(tmp_path / "ws")], check=True)
    (tmp_path / "ws" / "deckz.yml").write_text("{}\n", encoding="utf8")
    (directory / "deck.yml").write_text("name: abc\n", encoding="utf8")
    return directory


def _fake(tmp_path: Path, deck: Path, mode: str) -> Callable[..., list[str]]:
    script = tmp_path / "fake_deckz.py"
    script.write_text(_FAKE_DECKZ, encoding="utf8")
    pdf = watches.handout(deck, "fr")
    return lambda *_: [sys.executable, str(script), str(pdf), mode]


def _until(condition: Callable[[], bool]) -> None:
    deadline = monotonic() + 10
    while not condition():
        assert monotonic() < deadline, "timed out"
        sleep(0.02)


def _watch(tmp_path: Path, deck: Path, mode: str) -> Watch:
    return Watch(deck.parent.parent, deck, "fr", _fake(tmp_path, deck, mode)())


def test_a_finished_build_announces_its_pdf(tmp_path: Path, deck: Path) -> None:
    watch = _watch(tmp_path, deck, "ok")
    try:
        _until(lambda: watch.snapshot().built == 1)

        snapshot = watch.snapshot()
        assert snapshot.state is State.BUILT
        assert snapshot.pdf_version == watch.pdf.stat().st_mtime_ns
        assert watch.pdf == deck / "pdf" / "abc-handout.pdf"
    finally:
        watch.stop()


def test_a_failed_build_keeps_its_error_lines(tmp_path: Path, deck: Path) -> None:
    watch = _watch(tmp_path, deck, "fail")
    try:
        _until(lambda: len(watch.snapshot().errors) == 2)

        snapshot = watch.snapshot()
        assert snapshot.state is State.FAILED
        assert snapshot.errors == (
            "x: compilation failed",
            "error: unknown variable: oops",
        )
        assert snapshot.pdf_version == 0
    finally:
        watch.stop()


def test_stop_interrupts_then_kills(
    tmp_path: Path, deck: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(watches, "_STOP_TIMEOUT", 0.5)
    gentle = _watch(tmp_path, deck, "ok")
    stubborn = _watch(tmp_path, deck, "stubborn")
    _until(lambda: gentle.snapshot().built > 0 and stubborn.snapshot().built > 0)

    gentle.stop()
    stubborn.stop()

    assert not gentle.alive()
    assert not stubborn.alive()
    _until(lambda: stubborn.snapshot().state is State.STOPPED)


def test_one_watch_per_workspace(tmp_path: Path, deck: Path) -> None:
    other = deck.parent / "other"
    other.mkdir()
    (other / "deck.yml").write_text("name: other\n", encoding="utf8")
    manager = Watches(_fake(tmp_path, deck, "ok"), idle_after=0)
    workspace = deck.parent.parent
    try:
        first = manager.watch(workspace, deck, "fr")
        assert manager.watch(workspace, deck, "fr") is first

        second = manager.watch(workspace, other, "fr")

        assert second is not first
        assert not first.alive()
        assert manager.get(workspace) is second
    finally:
        manager.stop_all()


def test_stop_idle_spares_followed_watches(tmp_path: Path, deck: Path) -> None:
    manager = Watches(_fake(tmp_path, deck, "ok"), idle_after=0)
    workspace = deck.parent.parent
    try:
        watch = manager.watch(workspace, deck, "fr")
        watch.follow()
        assert manager.stop_idle() == []

        watch.unfollow()

        assert manager.stop_idle() == [watch]
        assert not watch.alive()
        assert manager.get(workspace) is None
    finally:
        manager.stop_all()
