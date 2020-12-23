from pathlib import Path
from shutil import copytree
import sys
from typing import Any, List

import appdirs
from git import Repo
from pdfminer.high_level import extract_pages, extract_text
from pytest import fixture, mark


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / __name__
    tmp_dir = tmp_path / "data"
    copytree(data_dir, tmp_dir)
    Repo.init(str(tmp_dir))
    working_dir = tmp_dir / "company" / "abc"
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_dir))
    return working_dir


@mark.parametrize("args,n_pages", [(["p1"], 14)])
def test_run(
    working_dir: Path, monkeypatch: Any, args: List[str], n_pages: int
) -> None:
    from deckz.cli import main

    monkeypatch.setattr(sys, "argv", ["deckz", "run"] + args)

    try:
        main()
    except SystemExit as e:
        if e.code != 0:
            raise e

    with open(working_dir / "pdf" / "abc-p1-presentation.pdf", "rb") as fh:
        pages = list(extract_pages(fh))
    with open(working_dir / "pdf" / "abc-p1-presentation.pdf", "rb") as fh:
        text = extract_text(fh)
    assert len(pages) == n_pages
    assert "John Doe" in text
