import json
from pathlib import Path
from typing import Any

from pygit2 import init_repository

from deckz.cli import main


def _notebook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"cells": [], "metadata": {}}', encoding="utf8")


def test_list_prints_nothing_without_a_notebooks_directory(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    main(("labs", "list"))

    assert capsys.readouterr().out == ""


def test_list_prints_a_line_per_notebook_french_first(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    notebooks = tmp_path / "labs" / "notebooks"
    _notebook(notebooks / "nlp" / "embeddings" / "demo-en.ipynb")
    _notebook(notebooks / "nlp" / "embeddings" / "demo-fr.ipynb")
    _notebook(notebooks / "nlp" / "embeddings" / "hands-on-fr.ipynb")
    monkeypatch.chdir(tmp_path)

    main(("labs", "list"))

    assert capsys.readouterr().out == (
        "nlp/embeddings\tdemo\tfr\nnlp/embeddings\tdemo\ten\n"
        "nlp/embeddings\thands-on\tfr\n"
    )


def test_list_json_gives_each_notebook_its_file(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    _notebook(tmp_path / "labs" / "notebooks" / "python" / "intro" / "demo-fr.ipynb")
    monkeypatch.chdir(tmp_path)

    main(("labs", "list", "--json"))

    assert json.loads(capsys.readouterr().out) == {
        "notebooks_dir": "labs/notebooks",
        "notebooks": [
            {
                "lab": "python/intro",
                "kind": "demo",
                "language": "fr",
                "file": "labs/notebooks/python/intro/demo-fr.ipynb",
            }
        ],
    }
