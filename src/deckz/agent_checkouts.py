"""The rule that an agent changes a repository only from its own worktree.

Several Claude Code sessions sharing one checkout see each other's
uncommitted edits, commit them by mistake, and get each other's hook
reports. When `deckz.yml` sets `worktree.required_for_agents`, the main
checkout is the user's, and each session works in its own worktree
(`claude --worktree <name>`, or `deckz worktree add <name>` then Claude
Code's EnterWorktree with its path), from which `deckz worktree land` puts
its commits on the main checkout's branch. The hooks enforce it:

- `edit_denial` (PreToolUse on the edit tools): no edit of a file of the
  main checkout, nor of a worktree's file from a session still in the main
  checkout, whose hooks would run in the wrong checkout;
- `main_checkout_verdict` (PreToolUse on Bash, through
  `agent_hooks.bash_denial`): refuses what is clearly a change of the main
  checkout -- git and deckz commands other than read-only ones (`git merge
  --ff-only` and `deckz worktree` are), a redirection into it, a program
  of `_WRITERS` writing one of its files, a change of its environment
  (`uv sync`, `pip`, `npm install`) -- and lets everything else run, after
  a snapshot of its `git status` (`take_snapshot`);
- `main_changes_report` (PostToolUse on Bash): compares the main
  checkout's `git status` with the snapshot, and reports what the command
  changed, which the session may then restore (`git restore`, `rm`) and
  only that;
- `session_start_context` (SessionStart): tells a session starting in the
  main checkout to create its worktree first;
- `create_worktree`/`remove_worktree` (WorktreeCreate/WorktreeRemove):
  Claude Code's own worktrees (`claude --worktree`, EnterWorktree, a
  subagent's isolation) are `deckz worktree`'s, builds included.

A change the snapshot can't see (an ignored file, a file outside the
repository) goes through: these are guard rails against an agent's
mistakes, not a sandbox.
"""

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings
    from .setting_up import SetupItem
    from .worktrees import Removed

# Programs that change the files they name: refused when one is in the main
# checkout. Every non-option argument is one, except where `_targets` says.
_WRITERS = frozenset(
    {
        "chmod",
        "chown",
        "cp",
        "install",
        "ln",
        "mkdir",
        "mv",
        "patch",
        "rm",
        "rmdir",
        "rsync",
        "tar",
        "tee",
        "touch",
        "truncate",
        "unlink",
        "unzip",
    }
)
# In-place editors: writers only with one of these options.
_IN_PLACE = {"sed": ("-i", "--in-place"), "perl": ("-i",)}
# `find` writes (or runs anything) with these; `sort` writes with -o.
_FIND_ACTIONS = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fls"}
)
_GIT_READ_ONLY = frozenset(
    {
        "blame",
        "cat-file",
        "check-attr",
        "check-ignore",
        "cherry",
        "count-objects",
        "describe",
        "diff",
        "fetch",
        "for-each-ref",
        "grep",
        "help",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "range-diff",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "var",
        "version",
        "whatchanged",
        "worktree",
    }
)
# Subcommands read-only with these first arguments (or none, for those in
# `_GIT_LISTING`).
_GIT_LISTING = {
    "branch": {"--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv"},
    "config": {"--get", "--get-all", "--get-regexp", "--list", "-l"},
    "remote": {"-v", "show", "get-url"},
    "stash": {"list", "show"},
    "tag": {"--list", "-l"},
}
_DECKZ_READ_ONLY = frozenset({"check", "search-sections", "show", "status", "worktree"})
_DECKZ_READ_ONLY_PAIRS = {
    "i18n": {"missing-en", "stale"},
    "setup": {"--check"},
}
_REDIRECTION = re.compile(r"^\d*>>?(.*)$")
_SNAPSHOTS = "deckz-bash-snapshots"
"""Directory, in the git common directory, of the snapshots of the Bash
calls running in the main checkout."""
_SHOWN = 10


@dataclass(frozen=True)
class Checkouts:
    """A repository's checkouts: its main one and its linked worktrees."""

    main: Path
    linked: tuple[Path, ...]

    def root_of(self, path: Path) -> Path | None:
        """The checkout `path` is in: the deepest one containing it.

        Returns:
            Its root, None outside every checkout.
        """
        roots = [
            root for root in (self.main, *self.linked) if path.is_relative_to(root)
        ]
        return max(roots, key=lambda root: len(root.parts)) if roots else None

    def in_main(self, path: Path) -> bool:
        return self.root_of(path) == self.main


def checkouts(git_dir: Path) -> Checkouts:
    """Every checkout of `git_dir`'s repository, from `git worktree list`.

    Returns:
        Them, their paths resolved.
    """
    listing = subprocess.run(
        ["git", "-C", str(git_dir), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    roots = [
        Path(line.removeprefix("worktree ")).resolve()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    ]
    return Checkouts(roots[0], tuple(roots[1:]))


def _how_to(main: Path) -> str:
    return (
        "EnterWorktree with a name creates one and moves the session into it"
        f" ({main.parent}/{main.name}--<name>, branch ws/<name>, made by `deckz"
        " worktree add`; EnterWorktree with the path of an existing one moves into"
        " it); work and commit there, and `deckz worktree land` puts the commits on"
        " the main checkout's branch."
    )


def _required(settings: "GlobalSettings") -> bool:
    return settings.worktree.required_for_agents


def session_start_context(settings: "GlobalSettings", cwd: Path) -> str | None:
    """What a session starting in the main checkout must know.

    Returns:
        The instructions, None if the rule is off or `cwd` is in a worktree.
    """
    if not _required(settings):
        return None
    found = checkouts(settings.paths.git_dir)
    if not found.in_main(cwd.resolve()):
        return None
    return (
        f"This session runs in {found.main}, the main checkout, which every agent"
        " session shares: you may read it, but change nothing in it (deckz.yml's"
        " worktree.required_for_agents; the hooks deny edits and writing commands"
        " here). Before your first change, work in a worktree of your own: "
        + _how_to(found.main)
    )


def edit_denial(settings: "GlobalSettings", payload: dict[str, Any]) -> str | None:
    """Why an edit tool may not change its file, if it may not.

    Returns:
        The reason, or None.
    """
    if not _required(settings):
        return None
    tool_input = payload.get("tool_input", {})
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return None
    cwd = Path(payload.get("cwd") or settings.paths.git_dir).resolve()
    path = Path(os.path.normpath(cwd / Path(target).expanduser()))
    found = checkouts(settings.paths.git_dir)
    root = found.root_of(path)
    if root is None:
        return None
    if root == found.main:
        return (
            f"{path} is in the main checkout, which every agent session shares:"
            " agents change files only in a worktree of their own. "
            + _how_to(found.main)
        )
    if found.in_main(cwd):
        return (
            f"This session still runs in the main checkout: switch into {root} with"
            " EnterWorktree (path: its root) before changing its files, so that"
            " the hooks run in it."
        )
    return None


def _resolve(word: str, cwd: Path) -> Path:
    return Path(os.path.normpath(cwd / Path(word).expanduser()))


def _strip_redirections(words: list[str], cwd: Path) -> tuple[list[str], list[Path]]:
    """Split a simple command's words from the files it redirects output to.

    Returns:
        The words left, and the redirections' targets.
    """
    kept: list[str] = []
    targets: list[Path] = []
    pending = False
    for word in words:
        if pending:
            targets.append(_resolve(word, cwd))
            pending = False
        elif match := _REDIRECTION.match(word):
            if match[1]:
                targets.append(_resolve(match[1], cwd))
            else:
                pending = True
        else:
            kept.append(word)
    return kept, targets


def _names_path_in(words: Iterable[str], cwd: Path, found: Checkouts) -> bool:
    for word in words:
        value = word.partition("=")[2] if word.startswith("--") else word
        if value.startswith("-") or not value:
            continue
        if found.in_main(_resolve(value, cwd)):
            return True
    return False


def _option_value(args: list[str], *names: str) -> str | None:
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            return args[i + 1]
        for name in names:
            if name.startswith("--") and arg.startswith(f"{name}="):
                return arg.partition("=")[2]
    return None


def _positionals(args: list[str]) -> list[str]:
    if "--" in args:
        i = args.index("--")
        return [a for a in args[:i] if not a.startswith("-")] + args[i + 1 :]
    return [a for a in args if not a.startswith("-")]


def _find_targets(_: str, args: list[str], cwd: Path) -> list[Path]:
    if not set(args) & _FIND_ACTIONS:
        return []
    starts = []
    for arg in args:
        if arg.startswith(("-", "(", "!")):
            break
        starts.append(_resolve(arg, cwd))
    return starts or [cwd]


def _sort_targets(_: str, args: list[str], cwd: Path) -> list[Path]:
    output = _option_value(args, "-o", "--output")
    return [_resolve(output, cwd)] if output else []


def _in_place_targets(program: str, args: list[str], cwd: Path) -> list[Path]:
    if not any(a.startswith(_IN_PLACE[program]) or a == "-pi" for a in args):
        return []
    # The script is the first word, unless -e/-f give it.
    rest = [a for a in args if not a.startswith("-")]
    if script := _option_value(args, "-e", "-f", "--expression", "--file"):
        return [_resolve(a, cwd) for a in rest if a != script]
    return [_resolve(a, cwd) for a in rest[1:]]


def _extracted_targets(program: str, args: list[str], cwd: Path) -> list[Path]:
    if program == "tar" and not _extracts(args):
        return []
    directory = _option_value(args, "-d", "-C", "--directory")
    return [_resolve(directory, cwd) if directory else cwd]


_SPECIAL_TARGETS = {
    "find": _find_targets,
    "sort": _sort_targets,
    "sed": _in_place_targets,
    "perl": _in_place_targets,
    "patch": _extracted_targets,
    "tar": _extracted_targets,
    "unzip": _extracted_targets,
}


def _targets(program: str, args: list[str], cwd: Path) -> list[Path]:
    """The files a writer (`_WRITERS`, an in-place editor, `find`, `sort`) changes.

    Returns:
        Their paths; empty for a program run without its writing option.
    """
    if program in _SPECIAL_TARGETS:
        return _SPECIAL_TARGETS[program](program, args, cwd)
    positionals = _positionals(args)
    if program in {"cp", "install", "ln", "rsync"}:
        if directory := _option_value(args, "-t", "--target-directory"):
            return [_resolve(directory, cwd)]
        return [_resolve(positionals[-1], cwd)] if positionals else []
    if program in {"chmod", "chown"}:
        positionals = positionals[1:]  # The mode or owner.
    return [_resolve(a, cwd) for a in positionals]


def _extracts(args: list[str]) -> bool:
    first = args[0] if args else ""
    return (
        "--extract" in args
        or "-x" in args
        or (not first.startswith("--") and "x" in first.lstrip("-"))
    )


def _git_read_only(args: list[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
    if i >= len(args):
        return True
    sub, rest = args[i], args[i + 1 :]
    if sub in _GIT_READ_ONLY:
        return True
    if sub == "merge":
        return "--ff-only" in rest
    if sub == "reflog":
        return not rest or rest[0] == "show"
    if sub in _GIT_LISTING:
        return not [a for a in rest if not a.startswith("-")] or bool(
            rest and rest[0] in _GIT_LISTING[sub]
        )
    return False


def _git_restores(args: list[str], cwd: Path, main: Path, own: set[str]) -> bool:
    # `git restore`/`checkout -- <paths>` putting back files of `own` only.
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
    if i >= len(args) or args[i] not in {"restore", "checkout"}:
        return False
    rest = args[i + 1 :]
    if args[i] == "checkout" and "--" not in rest:
        return False
    paths = _positionals(rest)
    return bool(paths) and _all_own(paths, cwd, main, own)


def _all_own(words: list[str], cwd: Path, main: Path, own: set[str]) -> bool:
    paths = [_resolve(word, cwd) for word in words]
    return all(
        path.is_relative_to(main) and path.relative_to(main).as_posix() in own
        for path in paths
    )


def _deckz_read_only(args: list[str]) -> bool:
    if {"--help", "-h", "--version"} & set(args):
        return True
    rest = [arg for arg in args if not arg.startswith("-") or arg == "--check"]
    if not rest:
        return True
    if rest[0] in _DECKZ_READ_ONLY:
        return True
    return rest[0] in _DECKZ_READ_ONLY_PAIRS and bool(
        set(rest[1:2]) & _DECKZ_READ_ONLY_PAIRS[rest[0]]
    )


def _changes_environment(program: str, args: list[str]) -> bool:
    # Its virtual environment or node_modules: ignored by git, so the
    # snapshot wouldn't see the change, which every session in the checkout
    # would run with.
    positionals = _positionals(args)
    sub = positionals[0] if positionals else ""
    if program == "uv":
        return bool(sub) and sub not in {"run", "help", "version", "tree"}
    if program in {"pip", "pip3"} or (program.startswith("python") and "pip" in args):
        return True
    return program in {"npm", "pnpm", "yarn"} and sub in {
        "install",
        "i",
        "ci",
        "add",
        "update",
        "remove",
        "uninstall",
    }


def _refusal(shown: str, what: str, main: Path) -> str:
    shown = shown if len(shown) <= 80 else shown[:77] + "..."
    return (
        f"`{shown}` {what}, in the main checkout ({main}), which is the user's: agents"
        " change files only in a worktree of their own. " + _how_to(main)
    )


def _unwrapped(words: list[str]) -> list[str]:
    # The command itself: without `VAR=value` prefixes, nor `uv run [options]`.
    while words and re.fullmatch(r"\w+=.*", words[0]):
        words = words[1:]
    if len(words) > 2 and Path(words[0]).name == "uv" and words[1] == "run":
        rest = words[2:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return _unwrapped(rest) if rest else words
    return words


def _git_verdict(
    shown: str, args: list[str], cwd: Path, found: Checkouts, own: set[str]
) -> str | None:
    here = cwd
    if "-C" in args and args.index("-C") + 1 < len(args):
        here = _resolve(args[args.index("-C") + 1], cwd)
    if not found.in_main(here):
        return None
    if _git_read_only(args) or _git_restores(args, here, found.main, own):
        return None
    return _refusal(shown, "changes the repository", found.main)


def _simple_verdict(
    words: list[str], cwd: Path, found: Checkouts, own: set[str]
) -> tuple[str | None, bool]:
    """Whether one simple command may run, and whether it may touch the main checkout.

    Returns:
        The refusal (None if it may run), and whether to take a snapshot.
    """
    words = _unwrapped(words)
    if not words:
        return None, False
    program, args = Path(words[0]).name, words[1:]
    main = found.main
    shown = " ".join(words)
    if program == "git":
        return _git_verdict(shown, args, cwd, found, own), False
    in_main = found.in_main(cwd)
    names_main = _names_path_in(args, cwd, found)
    if program == "deckz":
        if (in_main or names_main) and not _deckz_read_only(args):
            what = "builds or changes files" if "run" in args else "changes files"
            return _refusal(shown, what, main), False
        return None, False
    if in_main and _changes_environment(program, args):
        return _refusal(shown, "changes the Python or Node environment", main), False
    if program in _WRITERS or program in _SPECIAL_TARGETS:
        targets = [t for t in _targets(program, args, cwd) if found.in_main(t)]
        if targets and not (
            program == "rm" and _all_own(_positionals(args), cwd, main, own)
        ):
            return _refusal(shown, f"writes {targets[0]}", main), False
    return None, in_main or names_main


def main_checkout_verdict(
    settings: "GlobalSettings", script: list[list[str]], cwd: Path, own: set[str]
) -> tuple[str | None, Path | None]:
    """Whether a Bash command may run, and whether to watch the main checkout.

    Refuses what is clearly a change of the main checkout (see the module
    docstring), and lets the rest run, with a snapshot when one of its
    simple commands runs in the main checkout or names one of its paths.
    Follows `cd` from one simple command to the next, and git's `-C`.

    Args:
        settings: The settings of the checkout the session runs in.
        script: The command's simple commands, as `agent_hooks.commands` splits them.
        cwd: The directory the command starts in.
        own: The main checkout's files the session changed (`main_changes_report`):
            it may restore those.

    Returns:
        The refusal (None if it may run), and the main checkout to take a \
        snapshot of, if any.
    """
    if not _required(settings):
        return None, None
    found = checkouts(settings.paths.git_dir)
    cwd = cwd.resolve()
    watch = False
    for raw in script:
        words, redirected = _strip_redirections(raw, cwd)
        if into := [t for t in redirected if found.in_main(t)]:
            return _refusal(" ".join(raw), f"writes {into[0]}", found.main), None
        reason, touches = _simple_verdict(words, cwd, found, own)
        if reason:
            return reason, None
        watch = watch or touches
        program = Path(words[0]).name if words else ""
        if program in {"cd", "pushd"} and len(words) > 1 and words[1] != "-":
            cwd = _resolve(words[1], cwd)
        elif program == "cd" and len(words) == 1:
            cwd = Path.home()
    return None, found.main if watch else None


def _main_status(main: Path) -> dict[str, str]:
    """Every file of the main checkout that differs from its HEAD, with its hash.

    Changed or untracked (not ignored), from `git status`; a deleted
    file's hash is empty.

    Returns:
        The hashes, by path relative to `main`.
    """
    status = subprocess.run(
        ["git", "-C", str(main), "status", "--porcelain", "-z", "-uall"],
        capture_output=True,
        check=False,
    ).stdout.decode()
    entries = iter(status.split("\0"))
    paths = set()
    for entry in entries:
        if len(entry) > 3:
            paths.add(entry[3:])
            if entry[0] in "RC":  # The source path follows, with no status.
                paths.add(next(entries, ""))
    found = {}
    # deckz's own scratch directory, e.g. the hooks' session states.
    for path in {p for p in paths if p and not p.startswith(".check/")}:
        full = main / path
        found[path] = (
            hashlib.sha256(full.read_bytes()).hexdigest() if full.is_file() else ""
        )
    return found


def _snapshot_path(git_dir: Path, payload: dict[str, Any]) -> Path:
    common = subprocess.run(
        ["git", "-C", str(git_dir), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    key = (
        payload.get("tool_use_id")
        or hashlib.sha256(
            json.dumps([payload.get("session_id"), payload.get("tool_input")]).encode()
        ).hexdigest()
    )
    directory = (git_dir / common) / _SNAPSHOTS
    return directory / f"{re.sub(r'[^\w-]', '_', key)}.json"


def take_snapshot(
    settings: "GlobalSettings", payload: dict[str, Any], main: Path
) -> None:
    """Record the main checkout's `git status`, for `main_changes_report`."""
    path = _snapshot_path(settings.paths.git_dir, payload)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"main": str(main), "files": _main_status(main)}))


def main_changes_report(
    settings: "GlobalSettings", payload: dict[str, Any], own: list[str]
) -> str | None:
    """What a Bash command changed in the main checkout, from its snapshot.

    A file of `own` (reported already) isn't reported again, and leaves
    `own` once back to its HEAD version; a new change joins it.

    Args:
        settings: The settings of the checkout the session runs in.
        payload: The PostToolUse payload.
        own: The main checkout's files the session changed, updated in place.

    Returns:
        The report, or None if the command changed nothing there.
    """
    path = _snapshot_path(settings.paths.git_dir, payload)
    for stale in path.parent.glob("*.json"):  # A command interrupted, say.
        if stale.stat().st_mtime < time() - 3600:
            stale.unlink(missing_ok=True)
    if not path.is_file():
        return None
    snapshot = json.loads(path.read_text())
    path.unlink(missing_ok=True)
    main = Path(snapshot["main"])
    before: dict[str, str] = snapshot["files"]
    after = _main_status(main)
    changed = sorted(
        p for p in before.keys() | after.keys() if before.get(p) != after.get(p)
    )
    new = [p for p in changed if p not in own]
    # Still changed: a file back to its HEAD version is no longer the session's.
    own[:] = [p for p in [*own, *new] if p in after]
    if not new:
        return None
    lines = [f"- {p}" for p in new[:_SHOWN]]
    if len(new) > _SHOWN:
        lines.append(f"… and {len(new) - _SHOWN} more")
    return (
        f"Your command changed files in the main checkout ({main}), which is the"
        " user's:\n" + "\n".join(lines) + "\nMove each change to your worktree"
        " (create one if needed: " + _how_to(main) + "), then put the main"
        " checkout's file back: `git restore -- <path>` there for a tracked file,"
        " `rm <path>` for a new one (the hooks allow it for these files only). If"
        " a change isn't yours (the user may be editing there), say so instead."
    )


@dataclass(frozen=True)
class CreatedWorktree:
    path: Path
    unset: "list[SetupItem]"
    """What its `deckz setup` left missing or failed: only `shared` items."""


def create_worktree(settings: "GlobalSettings", name: str) -> CreatedWorktree:
    """Create the worktree Claude Code asks for, the `deckz worktree add` way.

    Its name is `name` with what `deckz worktree` doesn't take turned to
    `-` (Claude Code's may hold `/` and `.`); then `deckz setup` runs in it.
    A `deckz worktree` of that name already there is reused as it is:
    `claude --worktree <name> --resume <session>` asks for it again.

    Only what the worktree needs of its own (its setup steps, its git hooks) \
    blocks it. A `shared` item missing (a tool the machine lacks, `../deckz` \
    behind, a video never rendered) is missing from every checkout alike: \
    blocking on it would block every agent's worktree until a person fixes it, \
    so it's returned instead, for the caller to warn about.

    Returns:
        Its path, and the `shared` items its setup left missing or failed.

    Raises:
        WorktreeError: If its setup leaves something of its own missing or \
            failed (`deckz worktree add`'s own errors propagate too).
    """
    from .configuring.settings import GlobalSettings
    from .exceptions import WorktreeError
    from .setting_up import Status, incomplete, setup
    from .worktrees import add, worktrees

    name = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or "agent"
    for worktree in worktrees(settings):
        if worktree.name == name and worktree.path.is_dir():
            return CreatedWorktree(worktree.path, [])
    added = add(settings, name)
    items = setup(GlobalSettings.from_yaml(added.path))
    unset = [i for i in items if i.status in (Status.MISSING, Status.FAILED)]
    if incomplete(items, shared=False):
        problems = "; ".join(
            f"{i.name} {i.status.value}: {i.detail}" for i in unset if not i.shared
        )
        msg = (
            f"`deckz setup` left {added.path} incomplete ({problems}). Fix it there "
            "and run `deckz setup` again, then enter it by its path (EnterWorktree "
            f"with `path`); or remove it: `deckz worktree remove {name}`"
        )
        raise WorktreeError(msg)
    return CreatedWorktree(added.path, unset)


def remove_worktree(settings: "GlobalSettings", path: Path) -> "Removed":
    """Remove the worktree at `path`, as `deckz worktree remove` would.

    Refuses, as it does, while the worktree holds work nothing else has; \
    hands its builds over to the main checkout, as it does.

    Returns:
        What `deckz.worktrees.remove` did.

    Raises:
        WorktreeError: If `path` isn't one of `deckz worktree`'s.
    """
    from .exceptions import WorktreeError
    from .worktrees import remove, worktrees

    resolved = path.resolve()
    for worktree in worktrees(settings):
        if worktree.path.resolve() == resolved:
            return remove(settings, worktree.name)
    msg = f"{path} isn't a `deckz worktree`"
    raise WorktreeError(msg)
