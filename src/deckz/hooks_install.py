"""Write deckz's git hooks and Claude Code hooks into a repository.

Each installed git hook (in the repository's hooks directory: git's
`core.hooksPath` when it is set, else `.git/hooks/`) is a thin shell script
that shells back out to `deckz`: the pre-commit hook runs `deckz check
--staged` (so the checks apply to the commit about to be made, not the
unstaged working tree); the commit-msg hook runs `deckz hooks
check-commit-msg`, marking a commit that changes one side of a fr/en pair
without a `Lang-sync` trailer `Lang-sync: pending` (see
`deckz.analyzing.i18n_stale.mark_pending`).

A hook file deckz didn't write itself (no `_MARKER` line) is left alone
unless `force` is passed, so installing never silently clobbers a repo's
own pre-existing hook.

Every installed command runs `deckz` from the `PATH` when it is there, else
`uv run --quiet deckz` (deckz installed as a dependency of the repository's
own uv project, run from outside its virtual environment, e.g. by a git GUI
or a Claude Code session started without it).

The Claude Code hooks (`deckz.agent_hooks`) are added to
`.claude/settings.json` instead: unlike a git hook file, that file already
supports several independent hook registrations side by side (a list of
`{matcher, hooks: [...]}` groups per event), so there's nothing to refuse
to overwrite -- `install_claude_hooks` just updates the command of an event
deckz already registered (one calling `deckz hooks <name>`, whatever its
form) and leaves every other key of the file untouched.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pygit2 import Repository

from .exceptions import HookInstallRefusedError

if TYPE_CHECKING:
    from .configuring.settings import CiSettings

_MARKER = "# deckz-managed hook: safe to overwrite (deckz hooks install)"


def deckz_command(arguments: str) -> str:
    """A shell command running `deckz <arguments>`, from the `PATH` or through uv.

    Args:
        arguments: The deckz arguments, already shell-quoted.

    Returns:
        The command, replacing the shell with deckz either way, so its exit \
        code and output are deckz's own.
    """
    return (
        f"if command -v deckz >/dev/null 2>&1; then exec deckz {arguments}; "
        f"else exec uv run --quiet deckz {arguments}; fi"
    )


_COMMIT_MSG_ARGUMENTS = 'hooks check-commit-msg "$1"'
HOOKS: dict[str, str] = {
    "pre-commit": f"#!/bin/sh\n{_MARKER}\n{deckz_command('check --staged')}\n",
    "commit-msg": f"#!/bin/sh\n{_MARKER}\n{deckz_command(_COMMIT_MSG_ARGUMENTS)}\n",
}

_EDIT_TOOLS = "Edit|Write|MultiEdit|NotebookEdit"
# `deckz hooks post-bash` has nothing to do unless `pre-bash` left a snapshot
# (`agent_checkouts`): this skips its Python start-up after every other command.
_PENDING_SNAPSHOT = (
    '[ -n "$(ls -A "$(git rev-parse --git-common-dir 2>/dev/null)'
    '/deckz-bash-snapshots" 2>/dev/null)" ] || exit 0; '
)
_CLAUDE_HOOKS: list[dict[str, Any]] = [
    {
        "event": "PreToolUse",
        "matcher": "Bash",
        "subcommand": "pre-bash",
        "timeout": 10,
    },
    {
        "event": "PreToolUse",
        "matcher": _EDIT_TOOLS,
        "subcommand": "pre-edit",
        "timeout": 10,
    },
    {
        "event": "PostToolUse",
        "matcher": _EDIT_TOOLS,
        "subcommand": "post-edit",
        "timeout": 60,
        "statusMessage": "Checking the content file",
    },
    {
        "event": "PostToolUse",
        "matcher": "Bash",
        "subcommand": "post-bash",
        "timeout": 30,
        "guard": _PENDING_SNAPSHOT,
    },
    {
        "event": "PostToolUseFailure",
        "matcher": "Bash",
        "subcommand": "post-bash",
        "timeout": 30,
        "guard": _PENDING_SNAPSHOT,
    },
    {
        "event": "SessionStart",
        "subcommand": "session-start",
        "timeout": 30,
    },
    {
        "event": "Stop",
        "subcommand": "stop",
        "timeout": 60,
    },
    {
        "event": "WorktreeCreate",
        "subcommand": "worktree-create",
        "timeout": 600,
    },
    {
        "event": "WorktreeRemove",
        "subcommand": "worktree-remove",
        "timeout": 60,
    },
]


def hooks_dir(git_dir: Path) -> Path:
    """The directory git runs `git_dir`'s hooks from.

    Args:
        git_dir: Root of the repository.

    Returns:
        Its `core.hooksPath` (relative to `git_dir` unless absolute) when \
        set, else the `hooks/` of its git directory: `.git/hooks/`, or in a \
        linked worktree (whose `.git` is a file), the main checkout's.
    """
    repository = Repository(str(git_dir))
    config = repository.config
    if "core.hooksPath" in config and (hooks_path := config["core.hooksPath"]):
        return git_dir / Path(hooks_path).expanduser()
    # A linked worktree's own git directory names the shared one in `commondir`.
    private = Path(repository.path)
    common = private / "commondir"
    if common.is_file():
        return (private / common.read_text(encoding="utf8").strip()).resolve() / "hooks"
    return private / "hooks"


def install_hooks(git_dir: Path, *, force: bool = False) -> list[Path]:
    """Write every hook in `HOOKS` into `git_dir`'s hooks directory (`hooks_dir`).

    Args:
        git_dir: Root of the deckz-managed repository.
        force: Overwrite a hook file even if it isn't one deckz wrote.

    Returns:
        The written hook paths.

    Raises:
        HookInstallRefusedError: If an existing hook file doesn't carry \
            deckz's marker and `force` isn't set.
    """
    directory = hooks_dir(git_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in HOOKS.items():
        path = directory / name
        if (
            path.exists()
            and not force
            and _MARKER not in path.read_text(encoding="utf-8")
        ):
            msg = f"{path} already exists and isn't a deckz-managed hook"
            raise HookInstallRefusedError(msg)
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | 0o111)
        written.append(path)
    return written


def install_claude_hooks(git_dir: Path) -> Path:
    """Add deckz's generic Claude Code hooks to `git_dir`'s `.claude/settings.json`.

    Adds one `{matcher, hooks: [...]}` group per hook of `_CLAUDE_HOOKS`
    missing from the file; a hook already calling `deckz hooks <name>` (in
    any form, e.g. an older deckz's bare `deckz hooks stop`) gets the
    current command, timeout and matcher instead, so calling this
    repeatedly, or after the person edited the file by hand, never
    duplicates an entry. Every other key of an existing file -- other
    hooks, permissions, anything else -- is kept untouched.

    Args:
        git_dir: Root of the deckz-managed repository.

    Returns:
        The settings file's path.
    """
    path = git_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    hooks = settings.setdefault("hooks", {})
    for spec in _CLAUDE_HOOKS:
        groups = hooks.setdefault(spec["event"], [])
        command = spec.get("guard", "") + deckz_command(f"hooks {spec['subcommand']}")
        ours = False
        for group in groups:
            for hook in group.get("hooks", []):
                if f"deckz hooks {spec['subcommand']}" not in hook.get("command", ""):
                    continue
                ours = True
                hook["command"] = command
                hook["timeout"] = spec["timeout"]
                if "matcher" in spec:
                    group["matcher"] = spec["matcher"]
        if ours:
            continue
        entry: dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": spec["timeout"],
        }
        if "statusMessage" in spec:
            entry["statusMessage"] = spec["statusMessage"]
        group: dict[str, Any] = {"hooks": [entry]}
        if "matcher" in spec:
            group["matcher"] = spec["matcher"]
        groups.append(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path


_CI_PATH = Path(".github") / "workflows" / "deckz.yml"


def ci_workflow(ci: "CiSettings") -> str:
    """The GitHub Actions workflow `install_ci_workflow` writes.

    Returns:
        Its YAML text.
    """
    repo = "${{ github.event.repository.name }}"
    deckz_checkout = (
        f"""
      - name: Check out deckz next to it
        uses: actions/checkout@v7
        with:
          repository: {ci.deckz_repository}
          ref: {ci.deckz_ref}
          path: deckz
"""
        if ci.deckz_repository
        else ""
    )
    apt = (
        f"""
      - name: Install the system packages the dependencies need
        run: |
          apt-get update && apt-get install -y --no-install-recommends \\
            {" ".join(ci.apt_packages)}
"""
        if ci.apt_packages
        else ""
    )
    nightly = (
        f"""
      - name: Nightly checks
        if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
        run: uv run deckz check --plain {" ".join(ci.nightly_checks)}
"""
        if ci.nightly_checks
        else ""
    )
    return f"""{_MARKER.replace("hook", "workflow", 1)}
# Every contributor's commits get the checks the git hooks run, installed or not.
name: deckz

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    container: shuuchuu/deckz-ci:latest
    # apt brings in Debian's Python, without its headers: uv would build the
    # dependencies with no wheel (manimpango, pycairo) against it and fail.
    env:
      UV_PYTHON_PREFERENCE: only-managed
    defaults:
      run:
        working-directory: {repo}
    steps:
      - name: Check out the repository
        uses: actions/checkout@v7
        with:
          path: {repo}
          fetch-depth: 0
{deckz_checkout}{apt}
      # The container runs as root, the checkouts belong to the runner's user:
      # git refuses to read them until told they're safe.
      - name: Trust the checkouts
        run: git config --global --add safe.directory "*"

      - name: Install uv
        uses: astral-sh/setup-uv@v10.3.0

      - name: Install the dependencies
        run: uv sync

      - name: Content checks
        if: github.event_name == 'push' || github.event_name == 'pull_request'
        run: uv run deckz check --plain

      - name: Lang-sync trailers
        if: github.event_name == 'push' || github.event_name == 'pull_request'
        env:
          BEFORE: ${{{{ github.event.pull_request.base.sha || github.event.before }}}}
        run: |
          # A new branch has no "before": check its last commit only.
          case "$BEFORE" in
            "" | 0000000000000000000000000000000000000000) RANGE=HEAD~1..HEAD ;;
            *) RANGE="$BEFORE..HEAD" ;;
          esac
          uv run deckz hooks check-commits "$RANGE"
{nightly}"""


def install_ci_workflow(
    git_dir: Path, ci: "CiSettings", *, force: bool = False
) -> Path:
    """Write the GitHub Actions workflow running deckz's checks on every push.

    Args:
        git_dir: Root of the deckz-managed repository.
        ci: Its `ci` settings.
        force: Overwrite a workflow file deckz didn't write.

    Returns:
        The workflow's path.

    Raises:
        HookInstallRefusedError: If the file exists without deckz's marker \
            and `force` isn't set.
    """
    path = git_dir / _CI_PATH
    if (
        path.exists()
        and not force
        and "deckz-managed" not in path.read_text(encoding="utf-8")
    ):
        msg = f"{path} already exists and isn't a deckz-managed workflow"
        raise HookInstallRefusedError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ci_workflow(ci), encoding="utf-8")
    return path
