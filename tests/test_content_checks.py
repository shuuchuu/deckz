import json
from pathlib import Path

from pygit2 import init_repository

from deckz.analyzing.content_checks import (
    asset_credits,
    jinja_syntax,
    lab_format,
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


def _demo_with_cells(tmp_path: Path, *cells: dict) -> None:
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "demo-fr.ipynb",
        json.dumps({"metadata": {}, "cells": list(cells)}),
    )


def _code(*outputs: dict) -> dict:
    return {"cell_type": "code", "source": ["1"], "outputs": list(outputs)}


_SHOWN = {"output_type": "stream", "name": "stdout", "text": ["done\n"]}


def test_lab_outputs_flags_a_demo_cell_with_only_blank_outputs(
    tmp_path: Path,
) -> None:
    init_repository(str(tmp_path))
    _demo_with_cells(
        tmp_path,
        _code(_SHOWN),
        _code({"output_type": "stream", "name": "stdout", "text": ["\n", " \n"]}),
        _code(
            {"output_type": "stream", "name": "stderr", "text": "\n"},
            {"output_type": "execute_result", "data": {"text/plain": ["  "]}},
        ),
    )

    problems = lab_outputs(_settings(tmp_path))

    assert len(problems) == 1
    assert "demo-fr.ipynb" in problems[0]
    assert "[1], [2]" in problems[0]
    assert "only whitespace" in problems[0]
    assert "deckz labs outputs" in problems[0]


def test_lab_outputs_accepts_demo_cells_without_or_with_visible_outputs(
    tmp_path: Path,
) -> None:
    init_repository(str(tmp_path))
    _demo_with_cells(
        tmp_path,
        _code(_SHOWN),
        _code(),
        _code(
            {"output_type": "stream", "name": "stdout", "text": "\n"},
            {"output_type": "display_data", "data": {"image/png": "iVBOR"}},
        ),
        _code({"output_type": "error", "ename": "E", "evalue": "", "traceback": []}),
        _code({"output_type": "display_data", "data": {"text/html": ["<b>x</b>"]}}),
    )

    assert lab_outputs(_settings(tmp_path)) == []


def test_lab_outputs_does_not_flag_blank_outputs_in_a_hands_on(
    tmp_path: Path,
) -> None:
    # A hands-on has its own, stronger problem: any stored output.
    init_repository(str(tmp_path))
    _write(
        tmp_path / "labs" / "notebooks" / "topic" / "hands-on-fr.ipynb",
        json.dumps(
            {
                "metadata": {},
                "cells": [_code({"output_type": "stream", "text": "\n"})],
            }
        ),
    )

    problems = lab_outputs(_settings(tmp_path))

    assert len(problems) == 1
    assert "hands-on notebook has stored outputs" in problems[0]


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


def test_lab_format_flags_a_compact_notebook(tmp_path: Path) -> None:
    notebook = tmp_path / "labs" / "notebooks" / "topic" / "lab" / "demo-fr.ipynb"
    notebook.parent.mkdir(parents=True)
    notebook.write_text(json.dumps({"cells": [], "metadata": {}, "nbformat": 4}))
    settings = GlobalSettings(paths=GlobalPaths(current_dir=tmp_path, git_dir=tmp_path))

    problems = lab_format(settings)

    assert len(problems) == 1
    assert "deckz labs fmt" in problems[0]


_ENV = (
    "from jinja2 import Environment\n\n\n"
    "def environment_for(suffix: str) -> Environment:\n"
    "    env = Environment()\n"
    "    env.filters['image'] = lambda path: path\n"
    "    return env\n"
)


def test_jinja_syntax_flags_a_broken_tag_and_an_unknown_filter(
    tmp_path: Path,
) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "templates" / "jinja2" / "env.py", _ENV)
    content = tmp_path / "content" / "topic"
    _write(
        content / "fine.md", "# A\n\n{{ 'a.svg' | image }} {% raw %}{{ x{% endraw %}\n"
    )
    _write(content / "broken.md", "# A\n\nText {{ variables.depth\n")
    _write(
        content / "misspelt.md",
        "# A\n\n{{ 'a.svg' | imgae }}\n{% if x is od %}{% endif %}\n",
    )

    problems = jinja_syntax(_settings(tmp_path))

    assert len(problems) == 3
    assert problems[0].startswith(
        "content/topic/broken.md:3: unexpected end of template"
    )
    assert "{% raw %}" in problems[0]
    assert problems[1] == (
        "content/topic/misspelt.md:3: no filter named 'imgae' in"
        " templates/jinja2/env.py's environment: fix its name"
    )
    assert problems[2].startswith("content/topic/misspelt.md:4: no test named 'od'")


def test_jinja_syntax_needs_the_repository_environment(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "content" / "topic" / "broken.md", "{{ x\n")

    # Nothing renders without it: nothing to check.
    assert jinja_syntax(_settings(tmp_path)) == []

    _write(tmp_path / "templates" / "jinja2" / "env.py", "x = 1\n")
    problems = jinja_syntax(_settings(tmp_path))
    assert len(problems) == 1
    assert "environment_for" in problems[0]
