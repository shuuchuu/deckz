from studioz.notebooks import Change, cells, compare

from studioz import notebooks


def _code(source: str, *outputs: dict, id_: str | None = None) -> dict:
    metadata = {"id": id_} if id_ else {}
    return {
        "cell_type": "code",
        "metadata": metadata,
        "source": source,
        "outputs": list(outputs),
        "execution_count": 1,
    }


def _markdown(source: str, id_: str | None = None) -> dict:
    metadata = {"id": id_} if id_ else {}
    return {"cell_type": "markdown", "metadata": metadata, "source": source}


def test_markdown_keeps_math_whole_for_mathjax() -> None:
    html = notebooks.markdown(
        "Soit $a_i * b_i$ et $$\\sum_i x_i$$, `$x$` en code.\n\n"
        "\\begin{align} a &= b_1 \\\\ c &= d \\end{align}"
    )

    assert r"\(a_i * b_i\)" in html
    assert r"\[\sum_i x_i\]" in html
    assert "<code>$x$</code>" in html
    assert r"\begin{align} a &amp;= b_1 \\ c &amp;= d \end{align}" in html
    assert "<em>" not in html


def test_ansi_keeps_colors_and_a_progress_bars_last_state() -> None:
    html = notebooks.ansi("\x1b[1;31mError\x1b[0m <x>\n 10%|#\r 50%|#####\nab\bc")

    assert html == (
        '<span class="ansi-bold ansi-fg-1">Error</span> &lt;x&gt;\n 50%|#####\nac'
    )


def test_outputs_show_their_richest_type_and_merge_streams() -> None:
    (cell,) = cells(
        {
            "cells": [
                _code(
                    "x",
                    {"output_type": "stream", "name": "stdout", "text": ["a\n"]},
                    {"output_type": "stream", "name": "stdout", "text": "b\n"},
                    {
                        "output_type": "display_data",
                        "data": {"image/png": "iVBO\nRw==", "text/plain": "<Figure>"},
                    },
                    {
                        "output_type": "execute_result",
                        "data": {"text/html": "<table></table>", "text/plain": "df"},
                    },
                    {
                        "output_type": "display_data",
                        "data": {"application/vnd.jupyter.widget-view+json": {}},
                    },
                )
            ]
        }
    )

    assert [str(o) for o in cell.shown_outputs] == [
        '<pre class="output stdout">a\nb\n</pre>',
        '<div class="output image"><img src="data:image/png;base64,iVBORw==" alt=""'
        ' loading="lazy" decoding="async"></div>',
        '<div class="output html"><table></table></div>',
    ]


def test_cells_matched_by_id_are_one_cell_changed() -> None:
    before = {"cells": [_markdown("# Titre", "a"), _code("x = 1", id_="b")]}
    after = {
        "cells": [
            _markdown("# Titre", "a"),
            _code("x = 2", id_="b"),
            _markdown("Nouveau", "c"),
        ]
    }

    steps = compare(before, after)

    assert [step.kind for step in steps] == ["same", "changed", "added"]
    left, right = steps[1].lines
    assert [line.mark for line in left] == ["del"]
    assert [line.mark for line in right] == ["ins"]
    assert steps[1].source_changed
    assert not steps[1].outputs_changed


def test_without_ids_a_cell_in_place_of_another_is_changed() -> None:
    before = {"cells": [_markdown("Un"), _code("print(1)"), _markdown("Fin")]}
    after = {"cells": [_markdown("Un"), _code("print(2)"), _markdown("Fin")]}

    assert [step.kind for step in compare(before, after)] == ["same", "changed", "same"]


def test_only_outputs_changed_and_execution_counts_ignored() -> None:
    out = {"output_type": "execute_result", "data": {"text/plain": "1"}}
    before = {"cells": [_code("x", {**out, "execution_count": 3})]}
    rerun = {"cells": [_code("x", {**out, "execution_count": 7})]}
    changed = {"cells": [_code("x", {**out, "data": {"text/plain": "2"}})]}

    assert [step.kind for step in compare(before, rerun)] == ["same"]
    (step,) = compare(before, changed)
    assert step.kind == "changed"
    assert step.outputs_changed
    assert not step.source_changed


def test_a_reworded_paragraph_marks_its_words() -> None:
    step = Change(
        "changed",
        before=cells({"cells": [_markdown("Le chat dort.\nFin")]})[0],
        after=cells({"cells": [_markdown("Le chien dort.\nFin")]})[0],
    )

    left, right = step.lines

    assert [(str(line.html), line.mark) for line in left] == [
        ('Le <span class="word-del">chat</span> dort.', "del"),
        ("Fin", ""),
    ]
    assert (str(right[0].html), right[0].mark) == (
        'Le <span class="word-ins">chien</span> dort.',
        "ins",
    )


def test_the_frame_is_sandboxed_and_runs_studiozs_scripts_only() -> None:
    policy = notebooks.frame_headers("http://localhost:8421")["Content-Security-Policy"]

    assert policy.startswith("sandbox allow-scripts ")
    assert "allow-same-origin" not in policy
    assert "script-src http://localhost:8421/static/;" in policy
    assert "form-action 'none'" in policy
