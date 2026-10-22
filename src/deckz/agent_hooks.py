"""Claude Code hooks enforcing deckz-managed-repository invariants.

`deckz hooks install` (see `hooks_install.py`) wires these into
`.claude/settings.json`; `cli/hooks/*.py` reads each event's JSON payload
from stdin and calls into this module. A hook that fails on an unexpected
payload, or hits an internal error, must let the action through -- these
are guard rails for an agent session sharing a checkout with other
sessions, not a sandbox -- so `cli/hooks/*.py` catches broadly around
every call here instead of letting an exception propagate.

Two events need no repository-specific knowledge: PreToolUse/Bash (deny
skipping the git hooks, and staging everything or discarding uncommitted
changes -- several Claude Code sessions may share one checkout) and Stop
(flag a content file or lab notebook pair changed on one language side
only, reusing `analyzing.i18n_stale`'s pairing, and check the content
files changed by other means than the edit tools). What changed is a
worktree's own changes, in a worktree; elsewhere, the files the session's
edit tools changed: never another session's work.
PostToolUse/Edit converts an edited content file with the repo's own
`pandoc_command` and runs deckz's content checks on it alone. When
`deckz.yml` sets `worktree.required_for_agents`, PreToolUse/Edit,
PreToolUse/Bash and SessionStart also keep agents from changing the main
checkout (`agent_checkouts`). A target
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

import hashlib
import json
import os
import re
import shlex
from collections.abc import Generator
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path, PurePosixPath
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


def commands(script: str) -> list[list[str]]:
    """Split a shell script into its simple commands' words.

    Heredoc bodies (e.g. a commit message) are dropped first: they're data,
    not commands. So are duplications of a file descriptor (`2>&1`), whose
    `&` isn't a separator; `&>file` becomes `>file`. Other redirections
    stay words (`>`, `2>>log`, `>file`…).

    Returns:
        Each simple command's words.
    """
    script = _HEREDOC_RE.sub("", script)
    script = _FD_DUPLICATION_RE.sub(" ", script).replace("&>", ">")
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


def _builtin_denial(words: list[str], cwd: Path) -> str | None:
    """Why a simple command must never run in a deckz-managed repository.

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
    if lost := _discards(sub, args, cwd):
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
    docstring), then the main checkout's (`agent_checkouts`).

    Returns:
        The first denial reason found, or None if the command may run.
    """
    from .agent_checkouts import main_checkout_denial

    cwd = Path(payload.get("cwd") or settings.paths.git_dir)
    plugin = _deny_bash_plugin(settings)
    script = commands(payload.get("tool_input", {}).get("command", ""))
    for words in script:
        if reason := _builtin_denial(words, cwd):
            return reason
        if plugin is not None and (reason := plugin(words, cwd, settings)):
            return reason
    return main_checkout_denial(settings, script, cwd)


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
    those under `checks.opt_in` don't run. A problem is kept when its leading
    path (`Finding.path`) is one of `paths`.

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
    """Record an edited file, and check it if it's a content file.

    Records the file in the session's state, for `stop_report` outside a
    worktree; converts a content file and runs deckz's content checks on it
    (`_content_problems`), recording it as checked when it passes, so that
    `stop_report` doesn't check it again.

    Returns:
        A report to block the edit with, or None if nothing was found.
    """
    path = _edited_path(settings, payload)
    if path is None:
        return None
    git_dir = settings.paths.git_dir
    rel = path.relative_to(git_dir).as_posix()
    problems = (
        _content_problems(settings, [path]).get(rel)
        if _is_content(settings, path)
        else None
    )
    with _session_state(_session_state_file(settings, payload)) as state:
        edited: list[str] = state.setdefault("edited", [])
        if rel not in edited:
            edited.append(rel)
        if _is_content(settings, path) and not problems:
            state.setdefault("checked", {})[rel] = _file_hash(
                git_dir, PurePosixPath(rel)
            )
    if not problems:
        return None
    return _problems_message({rel: problems})


def _pairs(settings: "GlobalSettings") -> list[tuple[PurePosixPath, PurePosixPath]]:
    from .analyzing.i18n_stale import lang_pairs

    return lang_pairs(settings)


def _file_hash(git_dir: Path, path: PurePosixPath) -> str:
    full = git_dir / path
    return hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else ""


def _git_out(git_dir: Path, *args: str) -> str:
    from subprocess import run

    return run(
        ["git", "-C", str(git_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def _dirty_or_untracked(git_dir: Path) -> set[str]:
    """Every path (tracked-and-changed, or untracked) `git status` reports.

    Unlike `_changed_files` (used for Bash denials, where an untracked file
    is irrelevant: nothing can discard it), a new content file or notebook
    not yet committed is one the session changed.

    Returns:
        Each such path, relative to the git root; both sides of a rename.
    """
    entries = iter(
        _git_out(git_dir, "status", "--porcelain", "-z", "-uall").split("\0")
    )
    found = set()
    for entry in entries:
        if len(entry) > 3:
            found.add(entry[3:])
            if entry[0] in "RC":  # The source path follows, with no status.
                found.add(next(entries, ""))
    return found - {""}


def _worktree_changes(git_dir: Path, main: Path) -> set[str]:
    """What a worktree changed: uncommitted, or committed on its own branch.

    Its own branch: what the main checkout's branch doesn't have, since
    their merge base.

    Returns:
        The paths, relative to the git root.
    """
    branch = _git_out(main, "symbolic-ref", "--short", "HEAD").strip()
    base = _git_out(git_dir, "merge-base", branch or "HEAD", "HEAD").strip()
    committed = _git_out(git_dir, "diff", "--name-only", base, "HEAD").splitlines()
    return _dirty_or_untracked(git_dir) | set(committed)


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


def _stop_message(
    problems: dict[str, list[str]],
    unpaired: list[str],
    pair_of: dict[str, str],
    where: str,
) -> str | None:
    sections = []
    if problems:
        sections.append(
            f"Content files changed {where} fail deckz's checks:\n"
            + _problems_message(problems)
        )
    if unpaired:
        lines = _shown(
            [f"- {path} (not {pair_of[path]})" for path in unpaired],
            " (`deckz i18n stale`)",
        )
        sections.append(
            f"fr/en pairs changed on one side only {where}:\n"
            + "\n".join(lines)
            + "\nPort each change to the other language, or say why it is"
            " one-sided (a typo, a phrasing fix) and stop."
        )
    return "\n\n".join(sections) or None


def stop_report(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Flag the changes to content files: one-sided, or failing the checks.

    In a linked worktree, the changes are the worktree's: whatever `git
    status` reports, and the commits on its branch the main checkout's
    branch doesn't have, whichever session made them. Elsewhere, they are
    the files the session's edit tools changed (`post_edit_report`), and
    none when `worktree.required_for_agents` keeps agents from changing the
    main checkout. Flags a content file or lab notebook changed on one
    language side only (once per session), and runs the post-edit checks
    on each changed content file they haven't passed as it is now (written
    by a shell command, say, which no PostToolUse hook sees).

    Returns:
        A report to block the stop with, or None if nothing new was found.
    """
    from .agent_checkouts import checkouts
    from .utils import is_content_file

    if payload.get("stop_hook_active"):
        return None
    git_dir = settings.paths.git_dir
    main = checkouts(git_dir).main
    in_worktree = git_dir.resolve() != main
    if not in_worktree and settings.worktree.required_for_agents:
        return None
    with _session_state(_session_state_file(settings, payload)) as state:
        changed = (
            _worktree_changes(git_dir, main)
            if in_worktree
            else set(state.get("edited", []))
        )
        current = {path: _file_hash(git_dir, PurePosixPath(path)) for path in changed}
        fingerprint = hashlib.sha256(
            json.dumps(sorted(current.items())).encode()
        ).hexdigest()
        if state.get("fingerprint") == fingerprint:
            return None
        state["fingerprint"] = fingerprint
        if not any(
            is_content_file(PurePosixPath(path), settings.file_extensions)
            or path.endswith(".ipynb")
            for path in changed
        ):
            return None
        reported: list[str] = state.setdefault("reported", [])
        failed: dict[str, str] = state.setdefault("failed", {})
        checked: dict[str, str] = state.setdefault("checked", {})
        pair_of: dict[str, str] = {}
        for a, b in _pairs(settings):
            pair_of[str(a)] = str(b)
            pair_of[str(b)] = str(a)

        def exists(path: str) -> bool:
            return (git_dir / path).is_file()

        unpaired = sorted(
            path
            for path in changed & set(pair_of)
            if pair_of[path] not in changed
            and path not in reported
            # A file deleted with no sibling left behind is no gap.
            and (exists(path) or exists(pair_of[path]))
        )
        unchecked = sorted(
            path
            for path in changed
            if current[path]
            and current[path] not in {checked.get(path), failed.get(path)}
            and _is_content(settings, git_dir / path)
        )
        problems = (
            _content_problems(settings, [git_dir / path for path in unchecked])
            if unchecked
            else {}
        )
        for path in unchecked:
            (failed if path in problems else checked)[path] = current[path]
        reported.extend(unpaired)
    where = "in this worktree" if in_worktree else "this session"
    return _stop_message(problems, unpaired, pair_of, where)
