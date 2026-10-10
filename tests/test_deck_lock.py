import logging
from pathlib import Path
from threading import Event, Thread

from pytest import LogCaptureFixture

from deckz.pipelines import deck_lock


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
    with caplog.at_level(logging.INFO, logger="deckz.pipelines"):
        two = Thread(target=second)
        two.start()
        two.join(0.3)
        assert two.is_alive()
        release.set()
        one.join(5)
        two.join(5)

    assert order == ["first", "first done", "second"]
    assert "Waiting for another build of abc to finish" in caplog.text
