from pathlib import Path
from typing import Any

from deckz.cli import _presentation


def test_open_path_hands_the_path_to_the_desktop_opener(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(_presentation.sys, "platform", "linux")
    monkeypatch.setattr(
        _presentation, "Popen", lambda command, **_: calls.append(command)
    )

    _presentation.open_path(tmp_path)

    assert calls == [["xdg-open", str(tmp_path)]]


def test_rich_progress_nests_tasks_in_one_display() -> None:
    progress = _presentation.RichProgress()

    with progress.track("Building decks…", 2) as advance:
        display = progress._progress
        assert display is not None
        with progress.track("Compiling…", 1) as advance_inner:
            # No second live display, which would fight the first for the
            # terminal.
            assert progress._progress is display
            assert [task.description for task in display.tasks] == [
                "Building decks…",
                "Compiling…",
            ]
            advance_inner()
        assert [task.description for task in display.tasks] == ["Building decks…"]
        advance()

    assert progress._progress is None
