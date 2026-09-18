from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from subprocess import run

from ..exceptions import DeckzError
from .protocols import MarkdownConverterProtocol

_FILTER_PREFIX = "--lua-filter="


class PandocConverter(MarkdownConverterProtocol):
    def __init__(self, pandoc_command: Iterable[str]) -> None:
        self._pandoc_command = tuple(pandoc_command)

    def convert(self, source: Path, destination: Path) -> None:
        completed_process = run(
            [*self._pandoc_command, source.name, "-o", destination.name],
            cwd=source.parent,
            capture_output=True,
            encoding="utf8",
        )
        if completed_process.returncode != 0:
            msg = (
                f"pandoc failed to convert {source} to {destination}\n"
                f"{completed_process.stderr}"
            )
            raise DeckzError(msg)

    def fingerprint(self) -> str:
        parts = list(self._pandoc_command)
        for arg in self._pandoc_command:
            if arg.startswith(_FILTER_PREFIX):
                filter_path = Path(arg.removeprefix(_FILTER_PREFIX))
                if filter_path.is_file():
                    parts.append(sha256(filter_path.read_bytes()).hexdigest())
        return sha256("\0".join(parts).encode("utf8")).hexdigest()
