from pathlib import Path

from pygit2 import init_repository

from deckz.analyzing.content_checks import (
    asset_credits,
    lab_ids,
    lab_outputs,
    lab_pairs,
    lab_urls,
    raw_latex,
)
from deckz.configuring.settings import GlobalPaths, GlobalSettings


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_lab_ids_flags_a_notebook_with_no_id(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": []}',
    )

    problems = lab_ids(_settings(tmp_path))

    assert len(problems) == 1
    assert "demo-fr.ipynb" in problems[0]
    assert "no valid ID" in problems[0]


def test_lab_ids_flags_a_duplicate_id(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    metadata = '{"metadata": {"shuuchuu": {"id": "dup"}}, "cells": []}'
    _write(tmp_path / "labs" / "notebooks" / "a" / "demo-fr.ipynb", metadata)
    _write(tmp_path / "labs" / "notebooks" / "b" / "demo-fr.ipynb", metadata)

    problems = lab_ids(_settings(tmp_path))

    assert len(problems) == 1
    assert "dup" in problems[0]


def test_lab_pairs_flags_a_missing_sibling(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": []}',
    )

    problems = lab_pairs(_settings(tmp_path))

    assert len(problems) == 1
    assert "demo-en.ipynb" in problems[0]
    assert "missing" in problems[0]


def test_lab_pairs_flags_a_structural_difference(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": [{"cell_type": "code", "source": ["1"]}]}',
    )
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-en.ipynb",
        '{"metadata": {}, "cells": []}',
    )

    problems = lab_pairs(_settings(tmp_path))

    assert len(problems) == 1
    assert "1 cells in fr, 0 in en" in problems[0]


def test_lab_outputs_flags_a_hands_on_notebook_with_outputs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    code_cell = (
        '{"cell_type": "code", "source": ["1"], '
        '"outputs": [{"output_type": "execute_result", "data": {}}]}'
    )
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "hands-on-fr.ipynb",
        f'{{"metadata": {{}}, "cells": [{code_cell}]}}',
    )

    problems = lab_outputs(_settings(tmp_path))

    assert len(problems) == 1
    assert "hands-on-fr.ipynb" in problems[0]
    assert "stored outputs" in problems[0]


def test_lab_outputs_flags_a_demo_notebook_without_outputs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": [{"cell_type": "code", "source": ["1"], '
        '"outputs": []}]}',
    )

    problems = lab_outputs(_settings(tmp_path))

    assert len(problems) == 1
    assert "demo-fr.ipynb" in problems[0]
    assert "no stored outputs" in problems[0]


def test_lab_outputs_flags_a_demo_with_colab_private_outputs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {"colab": {"private_outputs": true}}, "cells": '
        '[{"cell_type": "code", "source": ["1"], '
        '"outputs": [{"output_type": "execute_result", "data": {}}]}]}',
    )

    problems = lab_outputs(_settings(tmp_path))

    assert len(problems) == 1
    assert "demo-fr.ipynb" in problems[0]
    assert "private_outputs" in problems[0]


def test_lab_outputs_accepts_a_demo_with_no_code_cells(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": [{"cell_type": "markdown", "source": ["# A"]}]}',
    )

    assert lab_outputs(_settings(tmp_path)) == []


def test_lab_outputs_accepts_a_hands_on_without_and_a_demo_with_outputs(
    tmp_path: Path,
) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "hands-on-fr.ipynb",
        '{"metadata": {}, "cells": [{"cell_type": "code", "source": ["1"], '
        '"outputs": []}]}',
    )
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        '{"metadata": {}, "cells": [{"cell_type": "code", "source": ["1"], '
        '"outputs": [{"output_type": "execute_result", "data": {}}]}]}',
    )

    assert lab_outputs(_settings(tmp_path)) == []


def test_asset_credits_flags_latex_in_a_credit_line(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "assets" / "photo.yml",
        'title: "Un \\\\textbf{titre}"\nauthor: Jane Doe\n',
    )

    problems = asset_credits(_settings(tmp_path))

    assert len(problems) == 1
    assert "photo.yml:1" in problems[0]


def test_asset_credits_accepts_a_plain_credit_line(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "assets" / "photo.yml", "title: A title\nlicense: CC-BY\n")

    assert asset_credits(_settings(tmp_path)) == []


def test_raw_latex_flags_a_tex_file(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "content" / "topic" / "notes.tex", r"\section{x}")

    problems = raw_latex(_settings(tmp_path))

    assert len(problems) == 1
    assert "notes.tex" in problems[0]


def test_raw_latex_flags_a_latex_block(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "content" / "topic" / "topic.md",
        "before\n\n```{=latex}\nraw\n```\n",
    )

    problems = raw_latex(_settings(tmp_path))

    assert len(problems) == 1
    assert "topic.md:3" in problems[0]


def test_lab_urls_does_nothing_without_a_publish_remote(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "content" / "topic" / "topic.md",
        "see github.com/shuuchuu/labs/blob/main/x.ipynb\n",
    )

    assert lab_urls(_settings(tmp_path)) == []


def test_lab_urls_flags_a_hand_written_link(tmp_path: Path) -> None:
    repo = init_repository(str(tmp_path))
    repo.remotes.create("labs", "git@github.com:shuuchuu/labs.git")
    _write(
        tmp_path / "content" / "topic" / "topic.md",
        "see github.com/shuuchuu/labs/blob/main/x.ipynb\n",
    )

    problems = lab_urls(_settings(tmp_path))

    assert len(problems) == 1
    assert "topic.md:1" in problems[0]
