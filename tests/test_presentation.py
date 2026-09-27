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
