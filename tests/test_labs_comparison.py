import json
from pathlib import Path

from deckz.labs.comparison import (
    code_difference,
    compare_pairs,
    missing_notebooks,
    pair_problems,
    variants,
)


def _write(path: Path, cells: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cells": cells, "metadata": {}}))


def _code(source: str) -> dict[str, object]:
    return {"cell_type": "code", "metadata": {}, "source": source}


def test_variants_groups_by_stem_and_language(tmp_path: Path) -> None:
    _write(tmp_path / "topic" / "demo-fr.ipynb", [])
    _write(tmp_path / "topic" / "demo-en.ipynb", [])
    _write(tmp_path / "topic" / "hands-on-fr.ipynb", [])

    found = variants(tmp_path)

    assert found[tmp_path / "topic" / "demo"] == {"fr", "en"}
    assert found[tmp_path / "topic" / "hands-on"] == {"fr"}


def test_variants_ignores_checkpoints(tmp_path: Path) -> None:
    _write(tmp_path / "topic" / ".ipynb_checkpoints" / "demo-fr-checkpoint.ipynb", [])
    _write(tmp_path / "topic" / "demo-fr.ipynb", [])

    found = variants(tmp_path)

    assert list(found) == [tmp_path / "topic" / "demo"]


def test_missing_notebooks_reports_the_absent_language(tmp_path: Path) -> None:
    _write(tmp_path / "topic" / "demo-fr.ipynb", [])

    assert list(missing_notebooks(tmp_path)) == [Path("topic/demo-en.ipynb")]


def test_code_difference_allows_consistent_renames() -> None:
    assert code_difference("x = 1\nprint(x)", "y = 1\nprint(y)") is None


def test_code_difference_rejects_inconsistent_renames() -> None:
    assert code_difference("x = 1\ny = 2", "a = 1\nb = 3") is not None


def test_code_difference_allows_string_literal_changes() -> None:
    assert code_difference('print("bonjour")', 'print("hello")') is None


def test_code_difference_none_when_identical() -> None:
    assert code_difference("x = 1", "x = 1") is None


def test_pair_problems_reports_cell_count_mismatch(tmp_path: Path) -> None:
    fr = tmp_path / "fr.ipynb"
    en = tmp_path / "en.ipynb"
    _write(fr, [_code("x = 1"), _code("y = 2")])
    _write(en, [_code("x = 1")])

    problems = pair_problems(fr, en)

    assert any("cells in fr" in p for p in problems)


def test_pair_problems_reports_differing_code(tmp_path: Path) -> None:
    fr = tmp_path / "fr.ipynb"
    en = tmp_path / "en.ipynb"
    _write(fr, [_code("x = 1")])
    _write(en, [_code("x = 2")])

    problems = pair_problems(fr, en)

    assert problems and "[0]" in problems[0]


def test_pair_problems_empty_when_translation_only(tmp_path: Path) -> None:
    fr = tmp_path / "fr.ipynb"
    en = tmp_path / "en.ipynb"
    _write(fr, [_code('x = "bonjour"')])
    _write(en, [_code('x = "hello"')])

    assert pair_problems(fr, en) == []


def test_compare_pairs_yields_only_differing_pairs(tmp_path: Path) -> None:
    _write(tmp_path / "ok-fr.ipynb", [_code("x = 1")])
    _write(tmp_path / "ok-en.ipynb", [_code("x = 1")])
    _write(tmp_path / "bad-fr.ipynb", [_code("x = 1")])
    _write(tmp_path / "bad-en.ipynb", [_code("x = 2")])

    results = dict(compare_pairs(tmp_path))

    assert list(results) == [Path("bad")]


def test_compare_pairs_restricts_to_given_dirs(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _write(tmp_path / "a" / "bad-fr.ipynb", [_code("x = 1")])
    _write(tmp_path / "a" / "bad-en.ipynb", [_code("x = 2")])
    _write(tmp_path / "b" / "bad2-fr.ipynb", [_code("x = 1")])
    _write(tmp_path / "b" / "bad2-en.ipynb", [_code("x = 2")])

    results = dict(compare_pairs(tmp_path, [tmp_path / "a"]))

    assert list(results) == [Path("a/bad")]
