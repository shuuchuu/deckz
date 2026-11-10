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
form), removes the hooks deckz no longer has (`_RETIRED`) and leaves every
other key of the file untouched.

A hook starts Python, imports deckz and reads `deckz.yml`: half a second,
after every tool call. Each command therefore starts with a shell test of
the hook's payload (`_filtered`, `_PENDING_SNAPSHOT`) that ends it at once
when deckz would have nothing to say.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pygit2 import Repository

from .exceptions import HookInstallRefusedError

if TYPE_CHECKING:
    from .configuring.settings import CiLabsSettings, CiSettings

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
# The main checkout's root, from any of its checkouts: `$m`, empty outside a
# repository.
_MAIN_ROOT = (
    "m=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); "
    "m=${m%/.git}; "
)
# `$m` as a whole path or a path's start: not the start of a sibling's name
# (`../repo--x`, a `deckz worktree`).
_NAMES_MAIN = '*"${m:-/}"[!A-Za-z0-9_.-]*'
# What `deckz hooks pre-bash` can deny: a git command, a deckz one or a task
# runner's (the repository's own denials), and a write into the main checkout
# -- which a command names by its path, a relative one or the home directory's,
# unless it runs there (its `cwd` is then in the payload).
_BASH_PATTERNS = f"*git*|*deckz*|*doit*|*../*|*'~'*|*'$HOME'*|{_NAMES_MAIN}"


def _filtered(patterns: str, command: str, *, setup: str = "") -> str:
    """A hook command that runs `command` only on a payload matching `patterns`.

    Args:
        patterns: `case` patterns, `|`-separated, the payload (JSON) must match.
        command: The command, which gets the payload on its standard input.
        setup: Shell commands setting what the patterns use.

    Returns:
        The shell command.
    """
    return (
        f'p=$(cat); {setup}case "$p" in {patterns}) ;; *) exit 0 ;; esac; '
        f"printf '%s' \"$p\" | {command}"
    )


_CLAUDE_HOOKS: list[dict[str, Any]] = [
    {
        "event": "PreToolUse",
        "matcher": "Bash",
        "subcommand": "pre-bash",
        "timeout": 10,
        "patterns": _BASH_PATTERNS,
        "setup": _MAIN_ROOT,
    },
    {
        "event": "PreToolUse",
        "matcher": _EDIT_TOOLS,
        "subcommand": "pre-edit",
        "timeout": 10,
        # It only denies an edit of the main checkout, or from it.
        "patterns": _NAMES_MAIN,
        "setup": _MAIN_ROOT,
    },
    {
        "event": "PostToolUse",
        "matcher": _EDIT_TOOLS,
        "subcommand": "post-edit",
        "timeout": 60,
        "statusMessage": "Checking the content file",
        # It only checks a content file: `patterns` comes from the
        # repository's content extensions (`install_claude_hooks`).
        "content_only": True,
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
_RETIRED = ("stop",)
"""Subcommands of `deckz hooks` an older deckz registered, removed on install:
the Stop hook's checks are the pre-commit hook's, and it asked for a
translation after each change, which `deckz i18n stale` keeps for when a
session in that language comes."""


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


def _hook_command(spec: dict[str, Any], extensions: Iterable[str]) -> str:
    command = deckz_command(f"hooks {spec['subcommand']}")
    if spec.get("content_only"):
        # The edited file's path ends a JSON string of the payload.
        patterns = "|".join(f'*{extension}\\"*' for extension in extensions)
        return _filtered(patterns, command)
    if "patterns" in spec:
        return _filtered(spec["patterns"], command, setup=spec.get("setup", ""))
    return spec.get("guard", "") + command


def _remove_retired(hooks: dict[str, Any]) -> None:
    for event in list(hooks):
        groups = hooks[event]
        for group in groups:
            group["hooks"] = [
                hook
                for hook in group.get("hooks", [])
                if not any(
                    f"deckz hooks {name}" in hook.get("command", "")
                    for name in _RETIRED
                )
            ]
        hooks[event] = [group for group in groups if group.get("hooks")]
        if not hooks[event]:
            del hooks[event]


def install_claude_hooks(git_dir: Path, extensions: Iterable[str] = (".md",)) -> Path:
    """Add deckz's generic Claude Code hooks to `git_dir`'s `.claude/settings.json`.

    Adds one `{matcher, hooks: [...]}` group per hook of `_CLAUDE_HOOKS`
    missing from the file; a hook already calling `deckz hooks <name>` (in
    any form, e.g. an older deckz's bare `deckz hooks stop`) gets the
    current command, timeout and matcher instead, so calling this
    repeatedly, or after the person edited the file by hand, never
    duplicates an entry. A hook deckz no longer has (`_RETIRED`) is removed,
    with its group and its event when nothing else is left in them. Every
    other key of an existing file -- other hooks, permissions, anything
    else -- is kept untouched.

    Args:
        git_dir: Root of the deckz-managed repository.
        extensions: Its content files' extensions (`file_extensions`): the
            post-edit hook runs for these files only.

    Returns:
        The settings file's path.
    """
    path = git_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    hooks = settings.setdefault("hooks", {})
    _remove_retired(hooks)
    extensions = tuple(extensions)
    for spec in _CLAUDE_HOOKS:
        groups = hooks.setdefault(spec["event"], [])
        command = _hook_command(spec, extensions)
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


_REPORTS = "../deckz-reports"
"""Where the scheduled steps write what failed, for `deckz hooks ci-report`."""
_NIGHTLY_CRON = "0 3 * * *"
_WEEKLY_CRON = "0 4 * * 0"
"""Sundays, an hour after the nightly checks: `github.event.schedule` tells \
the two runs apart."""
LABS_VENV = "../labs-venv"
"""The labs' own environment, next to the checkout as the reports are."""


def labs_check_command(labs: "CiLabsSettings", python: str = "") -> str:
    """The `deckz labs check` the scheduled job runs on `ci.labs`.

    Args:
        labs: `ci.labs`.
        python: The interpreter to give `--python`; the labs' environment's \
            by default.

    Returns:
        The command, without `uv run`.
    """
    python = python or f"{LABS_VENV}/bin/python"
    smoke = " --smoke" if labs.smoke else ""
    return (
        f"deckz labs check --python {python} --timeout {labs.timeout}{smoke} "
        "--deprecations " + " ".join(labs.notebooks)
    )


def labs_install_commands(labs: "CiLabsSettings") -> tuple[str, str]:
    """The commands creating the labs' environment and installing their libraries.

    Returns:
        `uv venv …` and `uv pip install …`. With extra indexes, each package \
        takes the best version any index has (uv's own default takes the \
        first index having the package at all: PyTorch's also serves numpy).
    """
    requirements = [] if labs.requirements is None else ["-r", labs.requirements]
    indexes = [arg for url in labs.index_urls for arg in ("--extra-index-url", url)]
    if indexes:
        indexes = ["--index-strategy", "unsafe-best-match", *indexes]
    install = " ".join(
        [
            "uv pip install --python",
            f"{LABS_VENV}/bin/python",
            *indexes,
            *requirements,
            *(f"'{p}'" for p in labs.packages),
        ]
    )
    return f"uv venv {LABS_VENV} --python {labs.python}", install


def _labs_step(ci: "CiSettings", dispatched: str) -> str:
    # Every Sunday, the labs `ci.labs` names, in an environment made anew.
    labs = ci.labs
    if labs is None:
        return ""
    venv, install = labs_install_commands(labs)
    check = f"uv run {labs_check_command(labs)}"
    if ci.report_to:
        run = f"""|
          # A failed install is the report, its log's end; else the labs'
          # output, when one fails.
          if ! {{ {venv} && {install}; }} > labs-install.txt 2>&1; then
            mkdir -p {_REPORTS}
            echo "Installing the labs' libraries failed:" > {_REPORTS}/labs.txt
            tail -n 60 labs-install.txt >> {_REPORTS}/labs.txt
            cat {_REPORTS}/labs.txt; exit 1
          fi
          {check} > labs.txt && cat labs.txt || {{
            cat labs.txt; mkdir -p {_REPORTS}; mv labs.txt {_REPORTS}/; exit 1
          }}"""
    else:
        run = f"""|
          {venv}
          {install}
          {check}"""
    return f"""
      # The labs, with their libraries' latest versions the requirements
      # allow, in an environment of their own: what a release breaks or
      # deprecates in them shows before a session does (`ci.labs`).
      - name: Run the labs
        if: (github.event.schedule == '{_WEEKLY_CRON}' || {dispatched}) && !cancelled()
        run: {run}
"""


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
    dispatched = "github.event_name == 'workflow_dispatch'"
    checks_command = f"uv run deckz check --plain {' '.join(ci.nightly_checks)}"
    checks_run = (
        f"""|
          # Their output is the report when they fail.
          {checks_command} > checks.txt && cat checks.txt || {{
            cat checks.txt; mkdir -p {_REPORTS}; mv checks.txt {_REPORTS}/; exit 1
          }}"""
        if ci.report_to
        else checks_command
    )
    nightly = (
        f"""
      - name: Nightly checks
        if: github.event.schedule == '{_NIGHTLY_CRON}' || {dispatched}
        run: {checks_run}
"""
        if ci.nightly_checks
        else ""
    )
    weekly = ci.builds_schedule == "weekly"
    build_cron = _WEEKLY_CRON if weekly else _NIGHTLY_CRON
    build_event = f"github.event.schedule == '{build_cron}' || {dispatched}"
    period, before = ("week", "7 days ago") if weekly else ("day", "24 hours ago")
    report = f" \\\n            --report {_REPORTS}/builds.md" if ci.report_to else ""
    sundays = (ci.builds and weekly) or ci.labs is not None
    weekly_cron = f'\n    - cron: "{_WEEKLY_CRON}"' if sundays else ""
    videos = (
        f"""
      - name: Fetch the published videos
        if: ({build_event}) && !cancelled()
        run: uv run deckz videos fetch --source https://github.com/{ci.videos_repository}
"""
        if ci.builds and ci.videos_repository
        else ""
    )
    cached = "".join(f"\n            {repo}/{path}" for path in ci.cache_paths)
    cache = (
        f"""
      # The last build's generated files, rebuilt only where stale; saved
      # again at the end of the job, under a key of its own.
      - name: Restore what the last builds generated
        if: ({build_event}) && !cancelled()
        uses: actions/cache@v6.1.0
        with:
          path: |{cached}
          key: deckz-builds-${{{{ github.run_id }}}}
          restore-keys: deckz-builds-
"""
        if ci.builds and ci.cache_paths
        else ""
    )
    user_variables = "".join(
        f"\n          {line}"
        for line in yaml.safe_dump(
            ci.user_variables, allow_unicode=True, sort_keys=False
        ).splitlines()
    )
    variables = (
        f"""
      # What each person's own variables.yml sets, with stand-in values.
      - name: Write the user variables the decks render with
        if: ({build_event}) && !cancelled()
        run: |
          DIR="${{XDG_CONFIG_HOME:-$HOME/.config}}/deckz"
          mkdir -p "$DIR"
          cat > "$DIR/variables.yml" <<'EOF'{user_variables}
          EOF
"""
        if ci.builds and ci.user_variables
        else ""
    )
    builds = (
        f"""{videos}{variables}{cache}
      # The decks the last {period}'s commits reach (the previous build built
      # the others), every deck when no commit is older than that. Built even
      # when a check failed: they say different things.
      - name: Build the decks changed in the last {period}
        if: ({build_event}) && !cancelled()
        run: |
          BASE=$(git rev-list -1 --before="{before}" HEAD)
          uv run deckz run decks ${{BASE:+--since "$BASE"}} --handout \\
            --no-presentation --no-part-handouts --lang {" ".join(ci.builds)}{report}
"""
        if ci.builds
        else ""
    )
    reporting = (
        f"""
      # An issue GitHub emails to `ci.report_to`, to paste to an agent.
      - name: Report the problems in an issue
        if: failure() && (github.event_name == 'schedule' || {dispatched})
        env:
          GITHUB_TOKEN: ${{{{ github.token }}}}
        run: uv run deckz hooks ci-report {_REPORTS}
"""
        if ci.report_to and (ci.builds or ci.nightly_checks or ci.labs)
        else ""
    )
    permissions = (
        """
    permissions:
      contents: read
      issues: write"""
        if reporting
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
    - cron: "{_NIGHTLY_CRON}"{weekly_cron}
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    container: shuuchuu/deckz-ci:latest{permissions}
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
{nightly}{builds}{_labs_step(ci, dispatched)}{reporting}"""


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
