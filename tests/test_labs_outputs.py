import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter
from pygit2 import init_repository
from pytest import raises

from deckz.cli import main
from deckz.configuring.settings import (
    GlobalPaths,
    GlobalSettings,
    LabsOutputsHook,
    LabsOutputsSettings,
    LabsSettings,
)
from deckz.exceptions import LabOutputsHookError, LabOutputsMismatchError
from deckz.labs.notebook import Notebook, canonical_dump
from deckz.labs.outputs import apply_executed_outputs, run_hooks, write_outputs


def _notebook(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _code_cell(**kwargs: Any) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": ["print(1)"],
        "execution_count": None,
        "outputs": [],
        **kwargs,
    }


def test_apply_executed_outputs_copies_execution_count_and_outputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                execution_count=1,
                outputs=[{"output_type": "execute_result", "data": {}}],
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["execution_count"] == 1
    assert notebook.cells[0]["outputs"] == [
        {"output_type": "execute_result", "data": {}}
    ]


def test_apply_executed_outputs_ignores_non_code_cells(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    markdown_cell = {"cell_type": "markdown", "metadata": {}, "source": ["# Title"]}
    path.write_text(canonical_dump(_notebook([markdown_cell])))
    notebook = Notebook(path)
    executed = _notebook([dict(markdown_cell)])

    apply_executed_outputs(notebook, executed)

    assert "outputs" not in notebook.cells[0]


def test_apply_executed_outputs_raises_on_cell_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell(), _code_cell()])))
    notebook = Notebook(path)
    executed = _notebook([_code_cell()])

    with raises(LabOutputsMismatchError):
        apply_executed_outputs(notebook, executed)


def test_apply_executed_outputs_merges_consecutive_stream_outputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "stream", "name": "stdout", "text": ["a"]},
                    {"output_type": "stream", "name": "stdout", "text": ["b\n"]},
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    outputs = notebook.cells[0]["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["text"] == ["ab\n"]


def test_apply_executed_outputs_keeps_different_stream_names_separate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "stream", "name": "stdout", "text": "out"},
                    {"output_type": "stream", "name": "stderr", "text": "err"},
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert len(notebook.cells[0]["outputs"]) == 2


def test_apply_executed_outputs_resolves_carriage_returns(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": "10%\r50%\r100%\ndone\n",
                    }
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["outputs"][0]["text"] == ["100%\n", "done\n"]


def test_apply_executed_outputs_keeps_crlf_lines(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": "a\r\nb\r\n10%\r50%\r\n",
                    }
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["outputs"][0]["text"] == ["a\n", "b\n", "50%\n"]


def _photo_like_png_b64() -> str:
    channels = [
        Image.effect_noise((300, 300), 40).filter(ImageFilter.GaussianBlur(6))
        for _ in range(3)
    ]
    buffer = BytesIO()
    Image.merge("RGB", channels).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_apply_executed_outputs_recompresses_large_images_by_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {
                        "output_type": "display_data",
                        "data": {"image/png": _photo_like_png_b64()},
                    }
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed, max_image_kb=1)

    data = notebook.cells[0]["outputs"][0]["data"]
    assert "image/png" not in data
    assert "image/jpeg" in data


def test_apply_executed_outputs_skips_recompression_when_disabled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    png_b64 = _photo_like_png_b64()
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "display_data", "data": {"image/png": png_b64}}
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed, recompress_images=False, max_image_kb=1)

    data = notebook.cells[0]["outputs"][0]["data"]
    assert data == {"image/png": png_b64}


def test_write_outputs_saves_notebook_in_canonical_style(tmp_path: Path) -> None:
    notebook_path = tmp_path / "demo.ipynb"
    notebook_path.write_text(
        json.dumps(_notebook([_code_cell()]), separators=(",", ":"))
    )
    executed_path = tmp_path / "executed.ipynb"
    executed_path.write_text(json.dumps(_notebook([_code_cell(execution_count=2)])))

    write_outputs(executed_path, notebook_path)

    written = json.loads(notebook_path.read_text())
    assert written["cells"][0]["execution_count"] == 2
    assert notebook_path.read_text() == canonical_dump(written)


def test_apply_executed_outputs_drops_an_output_showing_a_redacted_secret(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    shown = {"output_type": "stream", "name": "stdout", "text": ["ok\n"]}
    secret = {
        "output_type": "execute_result",
        "data": {"text/plain": ["'[deckz: redacted LAB_TOKEN]'"]},
    }
    executed = _notebook([_code_cell(execution_count=1, outputs=[shown, secret])])

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["outputs"] == [shown]


# A hook appending its own name to the first cell's outputs, to see what ran, in
# what order, on which notebook (its last argument, relative to the git root).
_HOOK = """
import json, sys
path = sys.argv[-1]
notebook = json.load(open(path))
notebook["cells"][0]["outputs"].append({"output_type": "stream", "text": sys.argv[1]})
open(path, "w").write(json.dumps(notebook))
print("rewrote", path)
"""


def _hooks_repo(tmp_path: Path, **hooks: LabsOutputsHook) -> GlobalSettings:
    init_repository(str(tmp_path))
    (tmp_path / "hook.py").write_text(_HOOK)
    return GlobalSettings(
        paths=GlobalPaths(current_dir=tmp_path, git_dir=tmp_path),
        labs=LabsSettings(outputs=LabsOutputsSettings(hooks=hooks)),
    )


def _hook(name: str, *notebooks: str) -> LabsOutputsHook:
    return LabsOutputsHook(run=(sys.executable, "hook.py", name), notebooks=notebooks)


def _lab_notebook(settings: GlobalSettings, relative: str) -> Path:
    path = settings.paths.labs_notebooks_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    return path


def _hook_names(path: Path) -> list[str]:
    return [o["text"] for o in json.loads(path.read_text())["cells"][0]["outputs"]]


def test_run_hooks_runs_the_matching_hooks_in_order_then_canonicalizes(
    tmp_path: Path,
) -> None:
    settings = _hooks_repo(
        tmp_path,
        every=_hook("every"),
        drift=_hook("drift", "monitoring/*/demo-*.ipynb"),
        other=_hook("other", "nlp/**"),
    )
    notebook = _lab_notebook(settings, "monitoring/drift/demo-fr.ipynb")

    ran = run_hooks(notebook, settings)

    assert ran == ["every", "drift"]
    assert _hook_names(notebook) == ["every", "drift"]
    assert notebook.read_text() == canonical_dump(json.loads(notebook.read_text()))


def test_run_hooks_runs_no_hook_and_leaves_a_notebook_nothing_matches(
    tmp_path: Path,
) -> None:
    settings = _hooks_repo(tmp_path, drift=_hook("drift", "monitoring/**"))
    notebook = _lab_notebook(settings, "nlp/embeddings/demo-fr.ipynb")
    outside = tmp_path / "elsewhere.ipynb"
    outside.write_text(json.dumps(_notebook([_code_cell()])))
    before = outside.read_text()

    assert run_hooks(notebook, settings) == []
    assert run_hooks(outside, settings) == []
    assert outside.read_text() == before  # Not even canonicalized.


def test_run_hooks_names_the_hook_its_output_and_the_fix_on_failure(
    tmp_path: Path,
) -> None:
    settings = _hooks_repo(
        tmp_path,
        broken=LabsOutputsHook(
            run=(sys.executable, "-c", "import sys; sys.exit('no report found')")
        ),
    )
    notebook = _lab_notebook(settings, "monitoring/drift/demo-fr.ipynb")

    with raises(LabOutputsHookError) as error:
        run_hooks(notebook, settings)

    message = str(error.value)
    assert "outputs hook broken failed (1)" in message
    assert "no report found" in message
    assert "deckz labs fmt labs/notebooks/monitoring/drift/demo-fr.ipynb" in message


def test_run_hooks_refuses_a_command_that_cant_start(tmp_path: Path) -> None:
    settings = _hooks_repo(
        tmp_path, missing=LabsOutputsHook(run=("no-such-command-deckz",))
    )
    notebook = _lab_notebook(settings, "a/b/demo-fr.ipynb")

    with raises(LabOutputsHookError, match="outputs hook missing can't run"):
        run_hooks(notebook, settings)


def test_run_hooks_refuses_a_hook_that_breaks_the_json(tmp_path: Path) -> None:
    settings = _hooks_repo(
        tmp_path,
        truncate=LabsOutputsHook(
            run=(sys.executable, "-c", "import sys; open(sys.argv[-1], 'w').write('{')")
        ),
    )
    notebook = _lab_notebook(settings, "a/b/demo-fr.ipynb")

    with raises(LabOutputsHookError, match="truncate left a notebook that isn't JSON"):
        run_hooks(notebook, settings)


def test_labs_outputs_runs_the_hooks_deckz_yml_declares(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    settings = _hooks_repo(tmp_path)
    notebook = _lab_notebook(settings, "monitoring/drift/demo-fr.ipynb")
    executed = tmp_path / "executed.ipynb"
    executed.write_text(json.dumps(_notebook([_code_cell(execution_count=1)])))
    (tmp_path / "deckz.yml").write_text(
        "labs:\n  outputs:\n    hooks:\n      cdn:\n"
        f"        run: [{sys.executable}, hook.py, cdn]\n"
        "        notebooks: ['monitoring/**']\n"
    )
    monkeypatch.chdir(tmp_path)

    main(("labs", "outputs", str(executed), str(notebook)))

    assert capsys.readouterr().out.splitlines()[-1] == "Ran outputs hook cdn"
    written = json.loads(notebook.read_text())
    assert written["cells"][0]["execution_count"] == 1
    assert _hook_names(notebook) == ["cdn"]
