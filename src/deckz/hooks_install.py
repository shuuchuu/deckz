"""Write deckz's git hooks and Claude Code hooks into a repository.

Each installed git hook (in `.git/hooks/`) is a thin shell script that
shells back out to `deckz`: the pre-commit hook runs `deckz check
--staged` (so the checks apply to the commit about to be made, not the
unstaged working tree); the commit-msg hook runs `deckz hooks
check-commit-msg`, refusing a commit that changes one side of a fr/en pair
without a `Lang-sync` trailer (see
`deckz.analyzing.i18n_stale.staged_one_sided_pairs`).

A hook file deckz didn't write itself (no `_MARKER` line) is left alone
unless `force` is passed, so installing never silently clobbers a repo's
own pre-existing hook.

The Claude Code hooks (`deckz.agent_hooks`) are added to
`.claude/settings.json` instead: unlike a git hook file, that file already
supports several independent hook registrations side by side (a list of
`{matcher, hooks: [...]}` groups per event), so there's nothing to refuse
to overwrite -- `install_claude_hooks` just skips an event deckz already
registered (matched by its exact `command` string) and leaves every other
key of the file untouched.
"""

import json
from pathlib import Path
from typing import Any

from .exceptions import HookInstallRefusedError

_MARKER = "# deckz-managed hook: safe to overwrite (deckz hooks install)"

HOOKS: dict[str, str] = {
    "pre-commit": f"#!/bin/sh\n{_MARKER}\nexec deckz check --staged\n",
    "commit-msg": f'#!/bin/sh\n{_MARKER}\nexec deckz hooks check-commit-msg "$1"\n',
}

_CLAUDE_HOOKS: dict[str, dict[str, Any]] = {
    "PreToolUse": {
        "matcher": "Bash",
        "command": "deckz hooks pre-bash",
        "timeout": 10,
    },
    "PostToolUse": {
        "matcher": "Edit|Write|MultiEdit",
        "command": "deckz hooks post-edit",
        "timeout": 60,
        "statusMessage": "Checking the content file",
    },
    "SessionStart": {
        "command": "deckz hooks session-start",
        "timeout": 30,
    },
    "Stop": {
        "command": "deckz hooks stop",
        "timeout": 30,
    },
}


def install_hooks(git_dir: Path, *, force: bool = False) -> list[Path]:
    """Write every hook in `HOOKS` into `git_dir`'s `.git/hooks/`.

    Args:
        git_dir: Root of the deckz-managed repository.
        force: Overwrite a hook file even if it isn't one deckz wrote.

    Returns:
        The written hook paths.

    Raises:
        HookInstallRefusedError: If an existing hook file doesn't carry \
            deckz's marker and `force` isn't set.
    """
    hooks_dir = git_dir / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in HOOKS.items():
        path = hooks_dir / name
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

    Adds one `{matcher, hooks: [...]}` group per event of `_CLAUDE_HOOKS`
    missing from the file; an event already carrying deckz's own command
    (matched exactly) is left as is, so calling this repeatedly, or after
    the person edited the file by hand, never duplicates an entry. Every
    other key of an existing file -- other hooks, permissions, anything
    else -- is kept untouched.

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
    for event, spec in _CLAUDE_HOOKS.items():
        groups = hooks.setdefault(event, [])
        if any(
            hook.get("command") == spec["command"]
            for group in groups
            for hook in group.get("hooks", [])
        ):
            continue
        entry: dict[str, Any] = {
            "type": "command",
            "command": spec["command"],
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
