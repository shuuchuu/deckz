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
only during the session, reusing `analyzing.i18n_stale`'s pairing, and
check the content files the session changed by other means than the edit
tools).
PostToolUse/Edit converts an edited content file with the repo's own
`pandoc_command` and runs deckz's content checks against it. A target
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
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.DOTALL
)
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
    not commands.

    Returns:
        Each simple command's words.
    """
    lexer = shlex.shlex(
        _HEREDOC_RE.sub("", script).replace("\n", " ; "),
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
    docstring).

    Returns:
        The first denial reason found, or None if the command may run.
    """
    cwd = Path(payload.get("cwd") or settings.paths.git_dir)
    plugin = _deny_bash_plugin(settings)
    for words in commands(payload.get("tool_input", {}).get("command", "")):
        if reason := _builtin_denial(words, cwd):
            return reason
        if plugin is not None and (reason := plugin(words, cwd, settings)):
            return reason
    return None


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
    from .components.factory import GlobalSettingsFactory
    from .exceptions import DeckzError

    scratch = path.with_name(f".{path.name}.deckz-hook-check{path.suffix}")
    try:
        GlobalSettingsFactory(settings).markdown_converter().convert(path, scratch)
    except DeckzError as error:
        return str(error)
    finally:
        scratch.unlink(missing_ok=True)
    return ""


def _is_content(settings: "GlobalSettings", path: Path) -> bool:
    return (
        path.suffix in settings.file_extensions
        and path.is_relative_to(settings.paths.git_dir)
        and path.is_file()
    )


def _content_problems(
    settings: "GlobalSettings", paths: list[Path]
) -> dict[str, list[str]]:
    """Convert each of `paths` and run deckz's content checks once for them all.

    Runs every check `deckz check` runs by default, i.e. not those listed \
    under `checks.opt_in`, and keeps the problems naming one of `paths`.

    Returns:
        Each problem, by the path (relative to the git root) it names.
    """
    from .components.factory import GlobalSettingsFactory

    git_dir = settings.paths.git_dir
    rels = [path.relative_to(git_dir).as_posix() for path in paths]
    problems: dict[str, list[str]] = {}
    for path, rel in zip(paths, rels, strict=True):
        if errors := _convert_errors(settings, path):
            problems.setdefault(rel, []).append(
                f"pandoc (this repo's `pandoc_command`) fails:\n{errors}"
            )
    checks = GlobalSettingsFactory(settings).checks_runner().checks()
    for name, check in checks.items():
        if name in settings.checks.opt_in:
            continue
        found = check()
        for rel in rels:
            if matches := [problem for problem in found if rel in problem]:
                problems.setdefault(rel, []).append(f"{name}:\n" + "\n".join(matches))
    return problems


def post_edit_report(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Convert an edited content file and run deckz's content checks on it.

    Does nothing for a file that isn't one of `settings.file_extensions`,
    or that doesn't exist (e.g. later deleted in the same tool call batch).
    A file found clean is recorded in the session's state, so that
    `stop_report` doesn't check it again.

    Returns:
        A report to block the edit with, or None if nothing was found.
    """
    path = Path(payload.get("tool_input", {}).get("file_path", "")).resolve()
    if not _is_content(settings, path):
        return None
    rel = path.relative_to(settings.paths.git_dir).as_posix()
    problems = _content_problems(settings, [path]).get(rel)
    if not problems:
        state_file = _session_state_file(settings, payload)
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state.setdefault("checked", {})[rel] = _file_hash(
                settings.paths.git_dir, PurePosixPath(rel)
            )
            _write_state(state_file, state)
        return None
    return f"{rel}: " + "\n".join(problems)


def _pairs(settings: "GlobalSettings") -> list[tuple[PurePosixPath, PurePosixPath]]:
    from .analyzing.i18n_stale import content_pairs, notebook_pairs

    return [*content_pairs(settings), *notebook_pairs(settings)]


def _file_hash(git_dir: Path, path: PurePosixPath) -> str:
    full = git_dir / path
    return hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else ""


def _head_hash(git_dir: Path, path: PurePosixPath, rev: str) -> str:
    from subprocess import run

    blob = run(
        ["git", "show", f"{rev}:{path.as_posix()}"],
        cwd=git_dir,
        capture_output=True,
        check=False,
    )
    return hashlib.sha256(blob.stdout).hexdigest() if blob.returncode == 0 else ""


def _head(git_dir: Path) -> str:
    from subprocess import run

    return run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_dir,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def _dirty_or_untracked(git_dir: Path) -> set[str]:
    """Every path (tracked-and-changed, or untracked) `git status` reports.

    Unlike `_changed_files` (used for Bash denials, where an untracked file
    is irrelevant: nothing can discard it), a new content file or notebook
    not yet committed is exactly what `_snapshot` must capture, so it isn't
    mistaken for having "always been there" -- a bare `_head_hash` lookup
    would find no blob for it and read it as unchanged.

    Returns:
        Each such path, as `git status --porcelain` prints it.
    """
    from subprocess import run

    status = run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=git_dir,
        capture_output=True,
        check=False,
    ).stdout.decode()
    return {entry[3:] for entry in status.split("\0") if len(entry) > 3}


def _session_state_file(settings: "GlobalSettings", payload: dict[str, Any]) -> Path:
    session = re.sub(r"[^\w-]", "_", payload.get("session_id") or "unknown")
    scratch = settings.paths.git_dir / ".check" / "hooks-sessions"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch / f"{session}.json"


def _write_state(state_file: Path, state: dict[str, Any]) -> None:
    # Atomic: hooks of parallel tool calls may read it while it's written.
    scratch = state_file.with_name(f".{state_file.name}.{os.getpid()}")
    scratch.write_text(json.dumps(state), encoding="utf-8")
    scratch.replace(state_file)


def _snapshot(settings: "GlobalSettings") -> dict[str, Any]:
    git_dir = settings.paths.git_dir
    paths = {str(path) for pair in _pairs(settings) for path in pair}
    # Only the dirty/untracked ones: a clean file's content is already a git
    # blob, _head_hash reads it from there on demand instead. Content files
    # too, paired or not: `stop_report` checks those the session changed.
    dirty = {
        path
        for path in _dirty_or_untracked(git_dir)
        if path in paths or PurePosixPath(path).suffix in settings.file_extensions
    }
    files = {path: _file_hash(git_dir, PurePosixPath(path)) for path in dirty}
    return {"head": _head(git_dir), "files": files, "reported": {}}


def session_start(settings: "GlobalSettings", payload: dict[str, Any]) -> None:
    """Snapshot the repo's paired files, for `stop_report` to diff against.

    A resumed or compacted session keeps its existing snapshot.
    """
    state_file = _session_state_file(settings, payload)
    if not state_file.exists():
        _write_state(state_file, _snapshot(settings))


def _session_changes(
    settings: "GlobalSettings", state: dict[str, Any], pair_of: dict[str, str]
) -> tuple[set[str], dict[str, str]]:
    """The paired or content files changed since the session's snapshot.

    Returns:
        Those paths, and the current hash of every path looked at (empty \
        for a deleted file).
    """
    git_dir = settings.paths.git_dir
    start_head: str = state["head"]
    start_files: dict[str, str] = state["files"]

    def watched(path: str) -> bool:
        return path in pair_of or PurePosixPath(path).suffix in settings.file_extensions

    candidates = set(start_files) | {
        path for path in _dirty_or_untracked(git_dir) if watched(path)
    }
    head = _head(git_dir)
    if head != start_head:
        from subprocess import run

        moved = run(
            ["git", "diff", "--name-only", start_head, head],
            cwd=git_dir,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
        candidates |= {path for path in moved if watched(path)}

    def start_hash(path: str) -> str:
        return (
            start_files[path]
            if path in start_files
            else _head_hash(git_dir, PurePosixPath(path), start_head)
        )

    current = {path: _file_hash(git_dir, PurePosixPath(path)) for path in candidates}
    return {path for path in candidates if current[path] != start_hash(path)}, current


def _stop_message(
    problems: dict[str, list[str]], unpaired: list[str], pair_of: dict[str, str]
) -> str | None:
    sections = []
    if problems:
        sections.append(
            "Content files changed this session fail the checks (fix them, as "
            "an edit's post-edit check would have said):\n"
            + "\n".join(
                f"{path}: " + "\n".join(found) for path, found in problems.items()
            )
        )
    if unpaired:
        lines = [f"- {path} changed, {pair_of[path]} didn't" for path in unpaired]
        sections.append(
            "fr/en pairs changed on one side only this session (port each change"
            " to the other language in the same session):\n"
            + "\n".join(lines)
            + "\nPort them, or, if a change is language-specific (a typo, a"
            " phrasing fix) or another session's, say so and stop."
        )
    return "\n\n".join(sections) or None


def stop_report(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Flag the session's changes to content files: one-sided, or failing checks.

    Compares the current working tree against the snapshot `session_start`
    took (or takes one now, if missing, reporting nothing this time). Flags
    a content file or lab notebook changed on one language side only, and
    runs the post-edit checks (`post_edit_report`) on every content file
    the session changed that they haven't passed as it is now: written by a
    shell command, say, which no PostToolUse hook sees.

    Returns:
        A report to block the stop with, or None if nothing new was found.
    """
    git_dir = settings.paths.git_dir
    state_file = _session_state_file(settings, payload)
    if not state_file.exists():
        _write_state(state_file, _snapshot(settings))
        return None
    state = json.loads(state_file.read_text(encoding="utf-8"))
    reported: dict[str, str] = state.setdefault("reported", {})
    checked: dict[str, str] = state.setdefault("checked", {})
    pair_of: dict[str, str] = {}
    for a, b in _pairs(settings):
        pair_of[str(a)] = str(b)
        pair_of[str(b)] = str(a)
    changed, current = _session_changes(settings, state, pair_of)

    def current_hash(path: str) -> str:
        if path in current:
            return current[path]
        return _file_hash(git_dir, PurePosixPath(path))

    unpaired = sorted(
        path
        for path in changed & set(pair_of)
        if pair_of[path] not in changed
        and reported.get(path) != current_hash(path)
        # A file deleted with no sibling left behind is no gap.
        and (current_hash(path) or current_hash(pair_of[path]))
    )
    unchecked = sorted(
        path
        for path in changed
        if current[path]
        and checked.get(path) != current[path]
        and reported.get(f"checks:{path}") != current[path]
        and _is_content(settings, git_dir / path)
    )
    if payload.get("stop_hook_active") or not (unpaired or unchecked):
        return None
    problems = _content_problems(settings, [git_dir / path for path in unchecked])
    for path in unchecked:
        if path in problems:
            reported[f"checks:{path}"] = current[path]
        else:
            checked[path] = current[path]
    for path in unpaired:
        reported[path] = current_hash(path)
    _write_state(state_file, state)
    return _stop_message(problems, unpaired, pair_of)
