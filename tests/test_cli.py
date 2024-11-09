import sys  # noqa: F401
from pathlib import Path
from shutil import copytree
from typing import Any
from unittest.mock import patch

import appdirs
from pdfminer.high_level import extract_pages, extract_text
from pygit2 import init_repository
from pytest import fixture

from deckz.cli import main


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / __name__
    tmp_dir = tmp_path / "data"
    copytree(data_dir, tmp_dir)
    init_repository(str(tmp_dir))
    working_dir = tmp_dir / "company" / "abc"
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_dir))
    return working_dir


def extract_info(pdf_path: Path) -> tuple[int, str]:
    with pdf_path.open("rb") as fh:
        pages = list(extract_pages(fh))
        fh.seek(0)
        text = extract_text(fh)
    return len(pages), text


def run_deckz(*args: str) -> None:
    with patch("sys.argv", ["deckz", *args]):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise e


def test_run(working_dir: Path) -> None:
    run_deckz("run", "p1")

    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def test_check_all(working_dir: Path) -> None:
    run_deckz("check-all")

    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text
