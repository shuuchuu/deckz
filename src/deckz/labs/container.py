"""Run a notebook for real in the published repository's dev container.

The published repository's `.devcontainer/devcontainer.json` (under
`paths.labs_published_dir`) is what GitHub Codespaces opens the notebooks in. This
builds its image (or pulls its `image`) and runs a notebook there with nbclient: a
real kernel, every shell line and magic run as written (`pip install`, `git
clone`, `apt install`), as the configuration's `remoteUser`, in
`/workspaces/<repository>`, capped to its `hostRequirements` -- what a trainee's
Run all does in a Codespace, and, for a notebook that needs no GPU, in Colab. Unlike
`labs.execution`'s runner, nothing is skipped: the container is thrown away after
the run, and nothing is mounted into it (the notebook and the runner go through
stdin), so nothing it does reaches this machine.

The image must hold `nbclient` and `ipykernel`.
"""

import hashlib
import json
import re
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..exceptions import LabContainerError
from .execution import report_lines

DEVCONTAINER_JSON = Path(".devcontainer") / "devcontainer.json"

# Runs inside the container, as `python -`, with the notebook and its cells' roles
# in place of the placeholders. Reports each failing cell as soon as it fails, so a
# run cut short by the timeout still reports what failed until then.
RUNNER = r"""
import json, pathlib, sys

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import DeadKernelError

EVENT = "\x1eQA "
NOTEBOOK = __NOTEBOOK__
ROLES = __ROLES__
OFFSET = __OFFSET__
NAME = __NAME__


running = [-1]


def started(cell, cell_index):
    running[0] = cell_index


def executed(cell, cell_index, execute_reply):
    for out in cell.get("outputs", []):
        if out.get("output_type") == "error":
            i = cell_index - OFFSET
            role = ROLES.get(str(i), "code")
            err = f"{out.get('ename')}: {out.get('evalue', '')}"[:300]
            print(EVENT + json.dumps([i, role, err]), file=sys.__stderr__, flush=True)
            break


path = pathlib.Path(NAME)
path.write_text(json.dumps(NOTEBOOK))
# A setup cell may kill its kernel on purpose, for Colab to restart it on a project
# it just installed ("run this cell twice"): the trainee then runs the notebook again,
# with the files the first run left. So does this, once.
for attempt in range(2):
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=None,
        allow_errors=True,
        kernel_name="python3",
        resources={"metadata": {"path": str(pathlib.Path.cwd())}},
        on_cell_execute=started,
        on_cell_executed=executed,
    )
    try:
        client.execute()
        break
    except DeadKernelError:
        event = ["kernel-died", running[0] - OFFSET, attempt == 0]
        print(EVENT + json.dumps(event), file=sys.__stderr__, flush=True)
"""

# Prepended as a code cell for `--smoke`: every Lightning Trainer capped to one short
# epoch, as `labs.execution`'s runner does.
SMOKE_CELL = """\
def __deckz_smoke():
  caps = {"max_epochs": 1, "limit_train_batches": 3, "limit_val_batches": 2}
  for name in ("lightning", "pytorch_lightning"):
    try:
      trainer = __import__(name).Trainer
    except ImportError:
      continue
    init = trainer.__init__

    def capped(self, *args, _init=init, **kwargs):
      kwargs.pop("max_steps", None)
      _init(self, *args, **{**kwargs, **caps})

    trainer.__init__ = capped


__deckz_smoke()
"""


@dataclass(frozen=True)
class Container:
    """How to start the dev container: its image and `docker run` options."""

    image: str
    user: str
    workspace: str
    limits: tuple[str, ...]


def _docker_memory(value: str) -> str:
    # devcontainer.json's "8gb" is docker's "8g".
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*", value.lower())
    if not match:
        msg = f"unreadable hostRequirements.memory: {value!r}"
        raise LabContainerError(msg)
    return match.group(1) + match.group(2)


def dev_container(published_dir: Path, repository: str) -> Container:
    """Build (or name) the image of `published_dir`'s dev container.

    Its `build.dockerfile` is built; a prebuilt `image` is used as it is,
    unless `customizations.deckz.dockerfile` names the Dockerfile it's built
    from, which is then built under the image's name. `docker build` reuses
    its cache, so this is quick when nothing changed.

    Returns:
        How to start it.

    Raises:
        LabContainerError: If there's no devcontainer.json, it's not plain JSON \
            or names neither an image nor a Dockerfile, or the build fails.
    """
    config_path = published_dir / DEVCONTAINER_JSON
    if not config_path.is_file():
        msg = f"no {config_path}: the published repository has no dev container"
        raise LabContainerError(msg)
    try:
        config: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        msg = f"{config_path} isn't plain JSON (no comments): {error}"
        raise LabContainerError(msg) from error
    user = config.get("remoteUser") or config.get("containerUser") or "root"
    host = config.get("hostRequirements", {})
    limits = []
    if "cpus" in host:
        limits += ["--cpus", str(host["cpus"])]
    if "memory" in host:
        limits += ["--memory", _docker_memory(host["memory"])]
    workspace = f"/workspaces/{repository}"
    config_dir = config_path.parent
    image = config.get("image")
    # A prebuilt image's own Dockerfile (`customizations.deckz.dockerfile`) builds
    # it here, under its name: a change is checked before CI publishes the image.
    local = config.get("customizations", {}).get("deckz", {}).get("dockerfile")
    build = {"dockerfile": local} if image and local else config.get("build", {})
    if image and not local:
        return Container(image, user, workspace, tuple(limits))
    if "dockerfile" not in build:
        msg = f"{config_path} names neither an `image` nor a `build.dockerfile`"
        raise LabContainerError(msg)
    dockerfile = config_dir / build["dockerfile"]
    context = config_dir / build.get("context", ".")
    digest = hashlib.sha256(str(config_dir.resolve()).encode()).hexdigest()[:12]
    tag = image or f"deckz-labs-{digest}"
    result = subprocess.run(
        ["docker", "build", "--quiet", "--tag", tag, "--file", dockerfile, context],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        msg = f"`docker build` of {dockerfile} failed:\n{tail}"
        raise LabContainerError(msg)
    return Container(tag, user, workspace, tuple(limits))


def runner_source(
    notebook: dict[str, Any], labels: list[str], name: str, *, smoke: bool
) -> str:
    """The runner the container executes, the notebook included.

    Returns:
        Python source.
    """
    roles = {str(i): role for i, role in enumerate(labels)}
    if smoke:
        cell = {
            "cell_type": "code",
            "metadata": {},
            "outputs": [],
            "source": SMOKE_CELL,
        }
        notebook = {**notebook, "cells": [cell, *notebook["cells"]]}
    return (
        RUNNER.replace("__NOTEBOOK__", repr(notebook))
        .replace("__ROLES__", repr(roles))
        .replace("__OFFSET__", "1" if smoke else "0")
        .replace("__NAME__", repr(name))
    )


def run_in_container(
    notebook: dict[str, Any],
    labels: list[str],
    name: str,
    container: Container,
    *,
    smoke: bool,
    timeout: int,
) -> Iterator[str]:
    """Run every code cell of `notebook` in `container`, as `name`.

    Yields:
        The run's report lines (see `labs.execution.report_lines`).
    """
    # Stored outputs would read as this run's: a demo stores its own.
    notebook = {
        **notebook,
        "cells": [
            {**cell, "outputs": []} if cell.get("cell_type") == "code" else cell
            for cell in notebook["cells"]
        ],
    }
    run_name = f"deckz-labs-check-{uuid.uuid4().hex[:12]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--name",
        run_name,
        "--user",
        container.user,
        "--workdir",
        container.workspace,
        *container.limits,
        container.image,
        "python",
        "-",
    ]
    source = runner_source(notebook, labels, name, smoke=smoke)
    try:
        proc = subprocess.run(
            command,
            input=source,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "kill", run_name], capture_output=True, check=False)
        stderr = e.stderr or b""
        yield f"  execution timed out after {timeout}s, cells run until then:"
        yield from report_lines(
            stderr.decode() if isinstance(stderr, bytes) else stderr, 0
        )
        return
    if proc.returncode and "\x1eQA " not in proc.stderr:
        # The runner itself failed (no nbclient in the image, the kernel died...).
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        yield f"  execution: the container exited with code {proc.returncode}:"
        yield from (f"    {line}" for line in tail.splitlines())
        return
    yield from report_lines(proc.stderr, proc.returncode)
