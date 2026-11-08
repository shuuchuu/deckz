"""What a lab notebook's runs need: values from the environment, and a hook.

A notebook's metadata (`labs.run.metadata_key`) can ask for `variables` and
`secrets`, each mapping a variable of the notebook, assigned `""` on a line of its
own, to the environment variable (or `.env` entry) a run fills it from, and for a
`hook`, a command of `labs.run.hooks` run before and after the run (e.g. to reset a
server the notebook writes to). `deckz labs gpu queue` and `deckz labs check
--container` honor them; the values travel only inside the copy of the notebook
they run, never on a command line, and a secret's value is replaced with
`REDACTED` in whatever comes back. A trainee's run leaves the `""` lines as
written: a notebook with needs must keep working without them.
"""

import json
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import Any

from ..exceptions import LabRunNeedsError

_logger = getLogger(__name__)

REDACTED = "[deckz: redacted {}]"
"""What a secret's value is replaced with, the environment variable's name in it."""

Runner = Callable[..., subprocess.CompletedProcess[str]]
"""`subprocess.run`'s signature: tests pass a fake one."""


@dataclass(frozen=True)
class RunNeeds:
    """What a notebook's runs need, from its metadata (`labs.run.metadata_key`).

    `variables` and `secrets` map a variable of the notebook, assigned `""` on
    a line of its own, to the environment variable whose value a run puts
    there; a secret's value is also redacted from what the run gives back.
    `hook` names a command of `labs.run.hooks`.
    """

    variables: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    hook: str | None = None

    @property
    def envs(self) -> dict[str, str]:
        """Every variable of the notebook to fill, and its environment variable."""
        return {**self.variables, **self.secrets}

    @property
    def secret_envs(self) -> tuple[str, ...]:
        """The environment variables of the secrets, sorted."""
        return tuple(sorted(set(self.secrets.values())))

    def unset(self) -> list[str]:
        """The environment variables asked for that aren't set (or are empty).

        Returns:
            Their names, sorted.
        """
        return sorted({env for env in self.envs.values() if not os.environ.get(env)})


def run_needs(nb: dict[str, Any], metadata_key: str) -> RunNeeds:
    """Read a notebook's `RunNeeds` from its metadata.

    Returns:
        Them, empty if the notebook has none.
    """
    node: Any = nb.get("metadata", {})
    for part in metadata_key.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return RunNeeds(
        variables=dict(node.get("variables", {})),
        secrets=dict(node.get("secrets", {})),
        hook=node.get("hook"),
    )


def fill_variables(nb: dict[str, Any], values: Mapping[str, str]) -> list[str]:
    """Set each `name = ""` line of `nb`'s code cells to `values[name]`, in place.

    Returns:
        The names whose line wasn't found exactly once.
    """
    found = dict.fromkeys(values, 0)
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        lines = source if isinstance(source, list) else source.splitlines(True)
        for i, line in enumerate(lines):
            for name, value in values.items():
                if line.strip() == f'{name} = ""':
                    indent = line[: len(line) - len(line.lstrip())]
                    newline = "\n" if line.endswith("\n") else ""
                    lines[i] = f"{indent}{name} = {json.dumps(value)}{newline}"
                    found[name] += 1
        cell["source"] = lines
    return [name for name, count in found.items() if count != 1]


def fill(nb: dict[str, Any], needs: RunNeeds) -> str | None:
    """Fill `nb`'s variables and secrets from the environment, in place.

    Only the set ones: an unset one keeps its `""` line, as a trainee's run does.

    Returns:
        What's wrong if a variable to fill hasn't exactly one `name = ""` line, \
        else None.
    """
    values = {
        variable: os.environ[env]
        for variable, env in needs.envs.items()
        if os.environ.get(env)
    }
    if unfilled := fill_variables(nb, values):
        lines = ", ".join(f'`{variable} = ""`' for variable in unfilled)
        return f"expected exactly one line {lines}"
    return None


def redact(text: str, envs: Iterable[str], *, strict: bool = True) -> str:
    """Replace the values of the environment variables `envs` in `text`.

    As is, and as escaped in a JSON string (with or without `ensure_ascii`).

    Args:
        text: What to redact.
        envs: The environment variables whose values to replace.
        strict: Whether an unset one is an error: it is when the value was \
            filled earlier (in another process), as it can't be found now. \
            Without it, an unset one is skipped: nothing filled it.

    Returns:
        The redacted text.

    Raises:
        LabRunNeedsError: If `strict` and one of `envs` isn't set.
    """
    for env in envs:
        value = os.environ.get(env)
        if not value:
            if not strict:
                continue
            msg = f"set {env} to redact its value from the run's notebooks and logs"
            raise LabRunNeedsError(msg)
        forms = {
            value,
            json.dumps(value, ensure_ascii=False)[1:-1],
            json.dumps(value)[1:-1],
        }
        for form in sorted(forms, key=len, reverse=True):
            text = text.replace(form, REDACTED.format(env))
    return text


def unknown_hook(needs: RunNeeds, hooks: Mapping[str, str]) -> str | None:
    """Whether a notebook names a hook that isn't declared.

    Returns:
        What's wrong if its hook isn't one of `hooks`, else None.
    """
    if needs.hook is None or needs.hook in hooks:
        return None
    return (
        f"hook {needs.hook!r} is not in labs.run.hooks: declare it"
        " in deckz.yml, or fix the name in the notebook's metadata"
    )


def run_hook(
    hook: str,
    hooks: Mapping[str, str],
    cwd: Path,
    run: Runner = subprocess.run,
) -> list[str]:
    """Run the command of `labs.run.hooks` named `hook`, from `cwd`, with `sh -c`.

    Returns:
        The lines it printed on stdout.

    Raises:
        LabRunNeedsError: If it exits with an error.
    """
    command = hooks[hook]
    _logger.info("Running hook %s: %s", hook, command)
    proc = run(
        ["sh", "-c", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = (proc.stdout or "").splitlines()
    for line in lines:
        _logger.info("%s: %s", hook, line)
    if proc.returncode:
        msg = (
            f"hook {hook} failed ({proc.returncode}): {command}\n"
            f"{proc.stdout or ''}{proc.stderr or ''}"
        )
        raise LabRunNeedsError(msg)
    return lines
