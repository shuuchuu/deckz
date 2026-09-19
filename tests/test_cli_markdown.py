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
    tmp_user_dir = tmp_path / "user"
    tmp_user_dir.mkdir()
    copytree(data_dir, tmp_dir)
    init_repository(str(tmp_dir))
    working_dir = tmp_dir / "company" / "abc"
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_user_dir))
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


def test_run_mixed_markdown_and_latex(working_dir: Path) -> None:
    run_deckz("run", "--parts", "p1")

    _, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert "Hello from Markdown, the answer is 42!" in text
    assert "Still plain" in text
    assert "Hi there, this shared section is Markdown too!" in text
    assert "Trainer-conditional content for Alice only." in text


def test_deps_reports_no_unused(working_dir: Path, capsys: Any) -> None:
    run_deckz("deps")

    out = capsys.readouterr().out
    assert "None." in out
    assert "greeting" not in out


def test_clean_latex_dry_run_keeps_used_markdown_section(working_dir: Path) -> None:
    shared_section = (
        working_dir.parent.parent / "shared" / "latex" / "greeting" / "hello.md"
    )
    assert shared_section.exists()

    run_deckz("clean", "latex", "--dry-run")

    assert shared_section.exists()
