"""Claude Code hooks enforcing deckz-managed-repository invariants.

`deckz hooks install` (see `hooks_install.py`) wires these into
`.claude/settings.json`; `cli/hooks/*.py` reads each event's JSON payload
from stdin and calls into this module. A hook that fails on an unexpected
payload, or hits an internal error, must let the action through -- these
are guard rails for an agent session sharing a checkout with other
sessions, not a sandbox -- so `cli/hooks/*.py` catches broadly around
every call here instead of letting an exception propagate.

PreToolUse/Bash needs no repository-specific knowledge: it denies skipping
the git hooks, and staging everything or discarding uncommitted changes
(several Claude Code sessions may share one checkout).
PostToolUse/Edit converts an edited content file with the repo's own
`pandoc_command` and runs deckz's content checks on it alone, and says
only what is new: a problem it already reported for the file isn't
repeated, and the checks of `checks.not_after_edit` (those whose verdict
depends on files written later: the other language's version, a chapter
referred to) wait for `deckz check`. Nothing runs when the session stops:
the pre-commit hook runs the checks on what gets committed, and the
commit-msg hook marks a change of one language only `Lang-sync: pending`,
for an agent as for a person (`analyzing.i18n_stale`). When
`deckz.yml` sets `worktree.required_for_agents`, PreToolUse/Edit,
PreToolUse/Bash, PostToolUse/Bash and SessionStart also keep agents from
changing the main checkout, and WorktreeCreate/WorktreeRemove make Claude
Code's worktrees `deckz worktree`'s (`agent_checkouts`). A target
repo's own `templates/hooks.py` (`GlobalPaths.hooks_module`) can add
further Bash denials -- the repo rules analogue of `templates/checks.py`
-- by exposing:

    def deny_bash(
        words: Sequence[str], cwd: Path, settings: GlobalSettings
    ) -> str | None: ...

called once per simple command of a Bash tool call, after deckz's own
built-in denials; the first reason found (deckz's own, then the plugin's)
wins. The module is optional.
"""

import json
import os
import re
import shlex
from collections.abc import Generator
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.DOTALL
)
_FD_DUPLICATION_RE = re.compile(r"\d*>&(?:\d+|-)")
_SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")"}
_GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
# `git commit` short options taking a value: in a cluster such as `-nm`, the
# letters after one of these are its value, not options.
_COMMIT_VALUE_OPTIONS = set("mFcCt")
_NO_VERIFY = (
    "Never skip the git hooks: they run the repository's checks. Fix what they"
    " report, or ask the user."
)


def _commit_no_verify(args: list[str]) -> bool:
    """Whether `git commit`'s arguments hold `-n`, alone or in a cluster.

    Returns:
        True if so; the letters after a value-taking option are its value.
    """
    for arg in args:
        if arg == "--":
            return False
        if not re.fullmatch(r"-[a-zA-Z]+", arg):
            continue
        for letter in arg[1:]:
            if letter == "n":
                return True
            if letter in _COMMIT_VALUE_OPTIONS:
                break
    return False


def _skips_hooks(words: list[str], sub: str, args: list[str]) -> bool:
    """Whether a git command skips the repository's hooks.

    Returns:
        True for `--no-verify`, `git commit -n`, or `-c core.hooksPath=...`.
    """
    if any(
        word.lower().startswith("core.hookspath=")
        for previous, word in pairwise(words)
        if previous == "-c"
    ):
        return True
    if sub not in {"commit", "push", "merge", "cherry-pick", "rebase", "am"}:
        return False
    return "--no-verify" in args or (sub == "commit" and _commit_no_verify(args))


def _mark_quoted(script: str) -> str:
    """Replace each `>` inside quotes, or escaped, by `QUOTED_GT`.

    Returns:
        The script, its quotes and everything else as they were.
    """
    from .agent_checkouts import QUOTED_GT

    out = []
    quote = ""
    chars = iter(script)
    for char in chars:
        if char == "\\" and quote != "'":
            escaped = next(chars, "")
            out.append(char + (QUOTED_GT if escaped == ">" else escaped))
            continue
        if quote and char == ">":
            out.append(QUOTED_GT)
            continue
        if char == quote:
            quote = ""
        elif not quote and char in "'\"":
            quote = char
        out.append(char)
    return "".join(out)


def commands(script: str, *, mark_quoted: bool = False) -> list[list[str]]:
    """Split a shell script into its simple commands' words.

    Heredoc bodies (e.g. a commit message) are dropped first: they're data,
    not commands. So are duplications of a file descriptor (`2>&1`), whose
    `&` isn't a separator; `&>file` becomes `>file`. Other redirections
    stay words (`>`, `2>>log`, `>file`…).

    Args:
        script: The shell script.
        mark_quoted: Replace a `>` that was inside quotes, or escaped, by
            `agent_checkouts.QUOTED_GT`, for a caller that looks for
            redirections: once split, `grep '>' a.md` and `grep > a.md` are
            the same words.

    Returns:
        Each simple command's words.
    """
    script = _HEREDOC_RE.sub("", script)
    script = _FD_DUPLICATION_RE.sub(" ", script).replace("&>", ">")
    if mark_quoted:
        script = _mark_quoted(script)
    lexer = shlex.shlex(
        script.replace("\n", " ; "),
        posix=True,
        punctuation_chars=";&|()",
    )
    lexer.whitespace_split = True
    out: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token in _SEPARATORS or set(token) <= set(";&|()"):
                out.append([])
            else:
                out[-1].append(token)
    except ValueError:  # Unbalanced quotes: let the shell complain.
        return []
    return [words for words in out if words]


def _git_call(words: list[str], cwd: Path) -> tuple[str, list[str], Path] | None:
    """The git subcommand of a simple command, if it runs git.

    Returns:
        `(subcommand, its arguments, the directory git runs in)`, or None.
    """
    while words and re.fullmatch(r"\w+=.*", words[0]):  # VAR=value prefixes
        words = words[1:]
    if not words or Path(words[0]).name != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            cwd = cwd / words[i + 1]
        i += 2 if words[i] in _GIT_OPTIONS_WITH_VALUE else 1
    if i >= len(words):
        return None
    return words[i], words[i + 1 :], cwd


def _changed_files(paths: list[str], cwd: Path) -> list[str]:
    """Tracked files under `paths` with uncommitted changes (staged or not).

    Returns:
        Their paths, as `git status` prints them.
    """
    from subprocess import run

    status = run(
        ["git", "status", "--porcelain", "--untracked-files=no", "--", *paths],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line[3:] for line in status.splitlines()]


def _discards(sub: str, args: list[str], cwd: Path) -> list[str]:
    """The uncommitted changes a git command would throw away.

    Returns:
        The changed files it would overwrite, empty if none.
    """
    options = [a for a in args if a.startswith("-")]
    if "--" in args:
        paths = args[args.index("--") + 1 :]
    else:
        paths = [a for a in args if not a.startswith("-")]
    if sub == "checkout":
        if "--" not in args:  # `git checkout <branch>` keeps changes, or refuses.
            paths = [p for p in paths if (cwd / p).exists()]
        return _changed_files(paths, cwd) if paths else []
    if sub == "restore":
        if "--staged" in options and not {"--worktree", "-W"} & set(options):
            return []
        return _changed_files(paths, cwd) if paths else []
    if sub == "reset" and "--hard" in options:
        return _changed_files([], cwd)
    if sub == "stash" and (
        not args or args[0] in {"push", "save"} or args[0][0] == "-"
    ):
        return [] if "--" in args else _changed_files([], cwd)
    return []


def _builtin_denial(
    words: list[str], cwd: Path, own: frozenset[str] = frozenset()
) -> str | None:
    """Why a simple command must never run in a deckz-managed repository.

    Args:
        words: The simple command's words.
        cwd: The directory it runs in.
        own: Files the session changed in the main checkout, which it may
            discard (`agent_checkouts.main_changes_report`).

    Returns:
        The reason, or None if it may run.
    """
    call = _git_call(words, cwd)
    if call is None:
        return None
    sub, args, cwd = call
    if _skips_hooks(words, sub, args):
        return _NO_VERIFY
    if sub == "add" and {"-A", "--all", ".", "-u", "--update", ":/"} & set(args):
        return (
            "Stage explicit paths (`git add <file>...`): other sessions' uncommitted"
            " changes share this checkout."
        )
    if sub == "commit" and any(
        a == "--all" or re.fullmatch(r"-[a-zA-Z]*a[a-zA-Z]*", a) for a in args
    ):
        return (
            "No `git commit -a`: stage explicit paths, other sessions' uncommitted"
            " changes share this checkout."
        )
    if sub == "clean" and not {"-n", "--dry-run"} & set(args):
        return (
            "No `git clean`: untracked files may be another session's work. Delete"
            " your own files by name."
        )
    if lost := [path for path in _discards(sub, args, cwd) if path not in own]:
        return (
            f"`git {sub}` would discard uncommitted changes, possibly another"
            f" session's: {', '.join(lost[:10])}. Undo your own edits by editing them"
            " back, or ask the user."
        )
    return None


def bash_denial(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Why `payload`'s Bash tool call must be denied, if any.

    Runs deckz's own built-in denials, then the target repo's own
    `deny_bash` from `templates/hooks.py` if it has one (see the module
    docstring), then the main checkout's (`agent_checkouts`), which takes
    a snapshot of it when the command may change it.

    Returns:
        The first denial reason found, or None if the command may run.
    """
    from .agent_checkouts import main_checkout_verdict, take_snapshot, unmarked

    cwd = Path(payload.get("cwd") or settings.paths.git_dir)
    plugin = _deny_bash_plugin(settings)
    marked = commands(
        payload.get("tool_input", {}).get("command", ""), mark_quoted=True
    )
    script = [[unmarked(word) for word in words] for words in marked]
    state_file = _session_state_file(settings, payload)
    own = frozenset(
        json.loads(state_file.read_text(encoding="utf-8")).get("main_changes", [])
        if state_file.is_file()
        else []
    )
    for words in script:
        if reason := _builtin_denial(words, cwd, own):
            return reason
        if plugin is not None and (reason := plugin(words, cwd, settings)):
            return reason
    reason, watched = main_checkout_verdict(settings, marked, cwd, set(own))
    if watched is not None:
        take_snapshot(settings, payload, watched)
    return reason


def post_bash_report(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """What a Bash command changed in the main checkout, if it was watched.

    See `agent_checkouts.main_changes_report`; the files it reports join
    the session's state, so that it may restore them.

    Returns:
        A report to give the agent, or None.
    """
    from .agent_checkouts import main_changes_report

    with _session_state(_session_state_file(settings, payload)) as state:
        own: list[str] = state.setdefault("main_changes", [])
        return main_changes_report(settings, payload, own)


def _deny_bash_plugin(settings: "GlobalSettings"):
    path = settings.paths.hooks_module
    if not path.is_file():
        return None
    from .components.hooks import load_hook

    return load_hook(path, "deckz._hooks", "deny_bash")


def _convert_errors(settings: "GlobalSettings", path: Path) -> str:
    """Convert `path` the way a real build would, minus rendering.

    Returns:
        pandoc's error output, empty if the conversion succeeds.
    """
    from tempfile import TemporaryDirectory

    from .components.factory import GlobalSettingsFactory
    from .exceptions import DeckzError

    # Outside the content tree: a hook killed mid-conversion once left its
    # scratch file next to the source, where `deckz check` then failed on it.
    with TemporaryDirectory(prefix="deckz-hook-") as scratch_dir:
        scratch = Path(scratch_dir) / path.name
        try:
            GlobalSettingsFactory(settings).markdown_converter().convert(path, scratch)
        except DeckzError as error:
            return str(error)
    return ""


def _pandoc_error(error: str) -> str:
    # pandoc's own message: without deckz's "failed to convert <path> to
    # <scratch file>" line, nor a Lua filter's stack traceback.
    lines = error.strip().splitlines()
    if lines and lines[0].startswith("pandoc failed to convert"):
        lines = lines[1:]
    if traceback := [i for i, line in enumerate(lines) if line == "stack traceback:"]:
        lines = lines[: traceback[0]]
    return "\n".join(line for line in lines if line.strip())


def _is_content(settings: "GlobalSettings", path: Path) -> bool:
    from .utils import is_content_file

    return (
        is_content_file(path, settings.file_extensions)
        and path.is_relative_to(settings.paths.git_dir)
        and path.is_file()
    )


def _content_problems(
    settings: "GlobalSettings", paths: list[Path]
) -> dict[str, list[str]]:
    """Convert each of `paths` and run deckz's content checks on them.

    The conversions run in parallel. Each check runs once, on `paths` alone
    when it takes them (see `ChecksRunner`), the whole repository otherwise;
    the opt-in ones (`ChecksSettings.runs_unnamed`) don't run. A problem is
    kept when its leading path (`Finding.path`) is one of `paths`.

    Returns:
        Each problem, as `[check] problem`, by the path (relative to the git \
        root) it is about.
    """
    from concurrent.futures import ThreadPoolExecutor

    from .components.factory import GlobalSettingsFactory

    git_dir = settings.paths.git_dir
    rels = [path.relative_to(git_dir).as_posix() for path in paths]
    problems: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=min(len(paths), 8) or 1) as pool:
        errors = list(pool.map(lambda path: _convert_errors(settings, path), paths))
    for rel, error in zip(rels, errors, strict=True):
        if error:
            problems.setdefault(rel, []).append(
                f"[pandoc] this repo's `pandoc_command` fails: {_pandoc_error(error)}"
            )
    runner = GlobalSettingsFactory(settings).checks_runner()
    for finding in runner.findings(paths=paths):
        if finding.path is not None and (rel := finding.path.as_posix()) in rels:
            problems.setdefault(rel, []).append(f"[{finding.check}] {finding.text}")
    return problems


_SHOWN = 10
"""How many paths a hook's report lists, and problems per path."""


def _shown(lines: list[str], more: str) -> list[str]:
    if len(lines) <= _SHOWN:
        return lines
    return [*lines[:_SHOWN], f"… and {len(lines) - _SHOWN} more{more}"]


def _problems_message(problems: dict[str, list[str]]) -> str:
    lines = []
    for path, found in list(problems.items())[:_SHOWN]:
        lines.append(f"{path}:")
        lines.extend(f"  {problem}" for problem in _shown(found, ""))
    if len(problems) > _SHOWN:
        lines.append(f"… and {len(problems) - _SHOWN} more files (`deckz check`)")
    return "\n".join(lines)


def _session_state_file(settings: "GlobalSettings", payload: dict[str, Any]) -> Path:
    session = re.sub(r"[^\w-]", "_", payload.get("session_id") or "unknown")
    scratch = settings.paths.git_dir / ".check" / "hooks-sessions"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch / f"{session}.json"


@contextmanager
def _session_state(state_file: Path) -> Generator[dict[str, Any]]:
    """The session's state, saved back on exit, unless the block raises.

    Locked meanwhile: the hooks of parallel tool calls update it at once.

    Yields:
        The state, a new one if the session has none yet.
    """
    import fcntl

    with state_file.with_name(f".{state_file.name}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state: dict[str, Any] = (
            json.loads(state_file.read_text(encoding="utf-8"))
            if state_file.is_file()
            else {}
        )
        yield state  # ruff: ignore[fallible-context-manager] (a failed hook leaves the state as it was)
        scratch = state_file.with_name(f".{state_file.name}.{os.getpid()}")
        scratch.write_text(json.dumps(state), encoding="utf-8")
        scratch.replace(state_file)


def _edited_path(settings: "GlobalSettings", payload: dict[str, Any]) -> Path | None:
    tool_input = payload.get("tool_input", {})
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return None
    cwd = Path(payload.get("cwd") or settings.paths.git_dir)
    path = (cwd / target).resolve()
    return path if path.is_relative_to(settings.paths.git_dir) else None


def post_edit_report(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Check an edited content file, and report what the edit brought.

    Converts the file and runs deckz's content checks on it
    (`_content_problems`), without those of `checks.not_after_edit`. A
    problem already reported to the session for this file, and still
    there, isn't reported again: the session's state keeps each file's
    last problems.

    Returns:
        A report to block the edit with, or None if nothing new was found.
    """
    path = _edited_path(settings, payload)
    if path is None or not _is_content(settings, path):
        return None
    rel = path.relative_to(settings.paths.git_dir).as_posix()
    skipped = tuple(f"[{name}] " for name in settings.checks.not_after_edit)
    problems = [
        problem
        for problem in _content_problems(settings, [path]).get(rel, [])
        if not problem.startswith(skipped)
    ]
    with _session_state(_session_state_file(settings, payload)) as state:
        reported: dict[str, list[str]] = state.setdefault("problems", {})
        known = set(reported.get(rel, []))
        if problems:
            reported[rel] = problems
        else:
            reported.pop(rel, None)
    new = [problem for problem in problems if problem not in known]
    if not new:
        return None
    message = _problems_message({rel: new})
    if still := len(problems) - len(new):
        message += (
            f"\n  … and {still} problem{'s' if still > 1 else ''} already reported"
            " for this file, still there"
        )
    return message


def session_start(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Prune old session states, and tell a session in the main checkout the rule.

    Returns:
        The context to give the session (`agent_checkouts`), or None.
    """
    from time import time

    from .agent_checkouts import session_start_context

    month_ago = time() - 30 * 24 * 3600
    for state in _session_state_file(settings, payload).parent.iterdir():
        if state.stat().st_mtime < month_ago:
            state.unlink(missing_ok=True)
    cwd = Path(payload.get("cwd") or settings.paths.git_dir)
    return session_start_context(settings, cwd)
