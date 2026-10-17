import logging
import sys
from pathlib import Path
from subprocess import PIPE, Popen
from threading import Event, Thread
from typing import TYPE_CHECKING, cast

from pytest import LogCaptureFixture

from deckz.components.assets_builder import AssetsBuilder
from deckz.pipelines import deck_lock

if TYPE_CHECKING:
    from deckz.components.protocols import CompilerProtocol


def test_a_second_build_of_a_deck_waits_for_the_first(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    # Each `deck_lock` opens the lock file anew: two builds in one process
    # contend like two processes would.
    build_dir = tmp_path / ".build"
    order: list[str] = []
    holding, release = Event(), Event()

    def first() -> None:
        with deck_lock(build_dir, "abc"):
            order.append("first")
            holding.set()
            release.wait(5)
            order.append("first done")

    def second() -> None:
        with deck_lock(build_dir, "abc"):
            order.append("second")

    one = Thread(target=first)
    one.start()
    assert holding.wait(5)
    with caplog.at_level(logging.INFO, logger="deckz.utils"):
        two = Thread(target=second)
        two.start()
        two.join(0.3)
        assert two.is_alive()
        release.set()
        one.join(5)
        two.join(5)

    assert order == ["first", "first done", "second"]
    assert "Waiting for another build of abc to finish" in caplog.text


def test_an_assets_build_waits_for_another_process_s(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    built = tmp_path / "built"
    module = tmp_path / "assets_builders.py"
    module.write_text(
        "from pathlib import Path\n"
        "DECKZ_HOOKS_VERSION = 1\n"
        "class Builder:\n"
        "    def build_assets(self):\n"
        f"        Path({str(built)!r}).write_text('built')\n"
        "    def watched_dirs(self):\n"
        "        return ()\n"
        "def assets_builders(assets_dir, compiler):\n"
        "    return [Builder()]\n",
        encoding="utf8",
    )
    lock = tmp_path / ".run" / "assets.lock"
    lock.parent.mkdir()
    holder = Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys\n"
            f"lock = open({str(lock)!r}, 'a')\n"
            "fcntl.flock(lock, fcntl.LOCK_EX)\n"
            "print('held', flush=True)\n"
            "sys.stdin.read()\n",
        ],
        stdin=PIPE,
        stdout=PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdin is not None
    assert holder.stdout.readline() == "held\n"
    builder = AssetsBuilder(module, tmp_path, cast("CompilerProtocol", None), lock)

    with caplog.at_level(logging.INFO, logger="deckz.utils"):
        build = Thread(target=builder.build_assets)
        build.start()
        build.join(0.3)
        assert build.is_alive()
        assert not built.exists()
        holder.stdin.close()
        holder.wait(5)
        build.join(5)

    assert built.read_text() == "built"
    assert "Waiting for another build's assets" in caplog.text
