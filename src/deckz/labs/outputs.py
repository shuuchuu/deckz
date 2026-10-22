"""Write an executed notebook's outputs back into its source, cell by cell.

Running a notebook (in Jupyter, Colab, or `deckz labs run --gpu`) produces a
copy with every code cell's `outputs` and `execution_count` filled in, plus
run metadata deckz never wants to store (timestamps, widget state). This
copies only the outputs themselves, merging each cell's consecutive stream
writes into one and resolving carriage returns, so a progress bar is stored
once, as its final state, as Colab shows it. An output showing a secret
`deckz labs gpu fetch` redacted (`deckz.labs.gpu.REDACTED`) is dropped.

Then the repository's `labs.outputs.hooks` run on the notebook written, for
what only the repository knows to do to its outputs (e.g. load a library's
JavaScript from a CDN instead of embedding it in every report), and the
notebook is written back in deckz's canonical style, whatever they changed.
"""

import json
import shlex
import subprocess
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import LabOutputsHookError, LabOutputsMismatchError
from .gpu import REDACTED
from .images import recompress_output_images
from .notebook import Notebook, cell_source, fmt_notebook

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings, LabsOutputsHook

_logger = getLogger(__name__)

_REDACTED_MARK = REDACTED.partition("{")[0]


def _resolve_carriage_returns(text: str) -> str:
    r"""Simulate a terminal: a `\r` discards what came before it on its line.

    A `\r` ending a line discards nothing: it's a `\r\n` line ending (IPython
    runs `!cmd` in a pty outside Colab), or a progress bar's last update.

    Returns:
        `text`, with each line collapsed to what a terminal would display.
    """
    return "\n".join(line.rstrip("\r").rsplit("\r", 1)[-1] for line in text.split("\n"))


def _stream_text(output: dict[str, Any]) -> str:
    return cell_source({"source": output.get("text", "")})


def _merge_stream_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive stream outputs of the same name into one.

    Returns:
        `outputs`, with each run of same-named `stream` outputs merged and \
        carriage returns resolved.
    """
    merged: list[dict[str, Any]] = []
    for output in outputs:
        is_stream = output.get("output_type") == "stream"
        if (
            is_stream
            and merged
            and merged[-1].get("output_type") == "stream"
            and merged[-1].get("name") == output.get("name")
        ):
            merged[-1] = {
                **merged[-1],
                "text": _stream_text(merged[-1]) + _stream_text(output),
            }
        else:
            merged.append(dict(output))
    for output in merged:
        if output.get("output_type") == "stream":
            output["text"] = _resolve_carriage_returns(_stream_text(output)).splitlines(
                keepends=True
            )
    return merged


def apply_executed_outputs(
    notebook: Notebook,
    executed: dict[str, Any],
    *,
    recompress_images: bool = True,
    max_image_kb: int = 200,
) -> None:
    """Copy `executed`'s cell outputs into `notebook`, in place.

    Only `outputs` and `execution_count` are copied, cell by cell, no run
    metadata. Consecutive stream outputs are merged and carriage returns
    resolved, and an output showing a redacted secret is dropped (see the
    module docstring).

    Args:
        notebook: The notebook to update, mutated in place; call `save()` \
            afterwards to write it.
        executed: The parsed, executed copy of the same notebook.
        recompress_images: Shrink large `image/png` outputs, see \
            `deckz.labs.images.recompress_output_images`.
        max_image_kb: Passed to `recompress_output_images`.

    Raises:
        LabOutputsMismatchError: If `notebook` and `executed` don't have the \
            same number of cells.
    """
    target_cells = notebook.cells
    executed_cells = executed.get("cells", [])
    if len(target_cells) != len(executed_cells):
        msg = (
            f"{notebook.path}: {len(target_cells)} cells, the executed copy "
            f"has {len(executed_cells)}"
        )
        raise LabOutputsMismatchError(msg)
    for target_cell, executed_cell in zip(target_cells, executed_cells, strict=True):
        if target_cell.get("cell_type") != "code":
            continue
        target_cell["execution_count"] = executed_cell.get("execution_count")
        outputs = [
            output
            for output in _merge_stream_outputs(executed_cell.get("outputs", []))
            if _REDACTED_MARK not in json.dumps(output, ensure_ascii=False)
        ]
        if recompress_images:
            recompress_output_images(outputs, max_image_kb=max_image_kb)
        target_cell["outputs"] = outputs


def write_outputs(
    executed_path: Path,
    notebook_path: Path,
    *,
    settings: "GlobalSettings | None" = None,
    recompress_images: bool = True,
    max_image_kb: int = 200,
) -> list[str]:
    """Load `notebook_path`, apply `executed_path`'s outputs, and save it.

    Then run the `labs.outputs.hooks` matching it (see `run_hooks`).

    Args:
        executed_path: Path to the executed copy, read for its cells' outputs.
        notebook_path: Path to the notebook to update and save.
        settings: The repository's settings, for its `labs.solution_heading` \
            (kept in sync on save) and `labs.outputs.hooks`; none, the \
            default heading and no hook.
        recompress_images: Passed to `apply_executed_outputs`.
        max_image_kb: Passed to `apply_executed_outputs`.

    Returns:
        The names of the hooks run.
    """
    heading = settings.labs.solution_heading if settings else "Solution"
    notebook = Notebook(notebook_path, solution_heading=heading)
    executed = json.loads(executed_path.read_text(encoding="utf-8"))
    apply_executed_outputs(
        notebook,
        executed,
        recompress_images=recompress_images,
        max_image_kb=max_image_kb,
    )
    notebook.save()
    return run_hooks(notebook_path, settings) if settings else []


def _hook_applies(hook: "LabsOutputsHook", path: Path, notebooks_dir: Path) -> bool:
    if not hook.notebooks:
        return True
    resolved, root = path.resolve(), notebooks_dir.resolve()
    if not resolved.is_relative_to(root):
        return False
    relative = resolved.relative_to(root)
    return any(relative.full_match(pattern) for pattern in hook.notebooks)


def run_hooks(notebook_path: Path, settings: "GlobalSettings") -> list[str]:
    """Run the `labs.outputs.hooks` matching a notebook, then canonicalize it.

    Each hook runs from the git root, given the notebook's path (relative to
    the git root when under it) as its last argument, in `deckz.yml`'s order.

    Args:
        notebook_path: The notebook whose outputs were just written.
        settings: The repository's settings.

    Returns:
        The names of the hooks run.

    Raises:
        LabOutputsHookError: If a hook can't start or exits non-zero, or \
            leaves a notebook that isn't JSON. The notebook keeps what the \
            hooks before it did.
    """
    git_dir = settings.paths.git_dir
    resolved = notebook_path.resolve()
    argument = (
        resolved.relative_to(git_dir.resolve()).as_posix()
        if resolved.is_relative_to(git_dir.resolve())
        else str(resolved)
    )
    ran: list[str] = []
    for name, hook in settings.labs.outputs.hooks.items():
        if not _hook_applies(hook, notebook_path, settings.paths.labs_notebooks_dir):
            continue
        command = [*hook.run, argument]
        _logger.info("Running outputs hook %s: %s", name, shlex.join(command))
        fix = (
            f"fix the hook (labs.outputs.hooks in deckz.yml), then run"
            f" `{shlex.join(command)}` and `deckz labs fmt {argument}` from"
            f" {git_dir}, or write the outputs back again"
        )
        try:
            proc = subprocess.run(
                command, cwd=git_dir, capture_output=True, text=True, check=False
            )
        except OSError as error:
            msg = f"{notebook_path}: outputs hook {name} can't run ({error}): {fix}"
            raise LabOutputsHookError(msg) from error
        for line in proc.stdout.splitlines():
            _logger.info("%s: %s", name, line)
        if proc.returncode:
            msg = (
                f"{notebook_path}: outputs hook {name} failed ({proc.returncode}),"
                f" after its outputs were written: {fix}\n{proc.stdout}{proc.stderr}"
            )
            raise LabOutputsHookError(msg.rstrip())
        ran.append(name)
    if ran:
        try:
            fmt_notebook(notebook_path, heading=settings.labs.solution_heading)
        except json.JSONDecodeError as error:
            msg = (
                f"{notebook_path}: outputs hook(s) {', '.join(ran)} left a notebook"
                f" that isn't JSON ({error}): fix the hook (labs.outputs.hooks in"
                " deckz.yml), then restore the notebook (`git checkout`) and write"
                " the outputs back again"
            )
            raise LabOutputsHookError(msg) from error
    return ran
