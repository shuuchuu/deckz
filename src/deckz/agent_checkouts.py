"""The rule that an agent changes a repository only from its own worktree.

Several Claude Code sessions sharing one checkout see each other's
uncommitted edits, commit them by mistake, and get each other's hook
reports. When `deckz.yml` sets `worktree.required_for_agents`, the main
checkout is for reading, and each session works in its own worktree
(`deckz worktree add <name>`, then Claude Code's EnterWorktree with its
path), from which `deckz worktree land` puts its commits on the main
checkout's branch. The hooks enforce it as strictly as they can:

- `edit_denial` (PreToolUse on the edit tools): no edit of a file of the
  main checkout, nor of a worktree's file from a session still in the main
  checkout, whose hooks would run in the wrong checkout;
- `main_checkout_denial` (called by `agent_hooks.bash_denial`): a command
  run in the main checkout, or naming one of its paths, must be read-only:
  a program of `_READ_ONLY` (minus its writing options), a read-only git
  or deckz subcommand, `git merge --ff-only` (landing), `git worktree`,
  `deckz worktree`; and no redirection may write into it;
- `session_start_context` (SessionStart): tells a session starting in the
  main checkout to create its worktree first.

A command can still write through a program the allowlist trusts (`sed`'s
`w` command, say): these are guard rails against an agent's mistakes, not a
sandbox.
"""

import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

_READ_ONLY = frozenset(
    {
        "[",
        "basename",
        "cat",
        "cd",
        "cmp",
        "column",
        "comm",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "egrep",
        "false",
        "fgrep",
        "file",
        "find",
        "grep",
        "head",
        "jq",
        "less",
        "ls",
        "md5sum",
        "nl",
        "pdffonts",
        "pdfinfo",
        "printf",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "sed",
        "sha1sum",
        "sha256sum",
        "sort",
        "stat",
        "tail",
        "test",
        "tree",
        "true",
        "type",
        "uniq",
        "wc",
        "which",
    }
)
# Options that make a program of `_READ_ONLY` write or run something.
_WRITING_OPTIONS = {
    "find": (
        "-delete",
        "-exec",
        "-execdir",
        "-ok",
        "-okdir",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-fls",
    ),
    "sed": ("-i", "--in-place"),
    "sort": ("-o", "--output"),
}
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
        f"`deckz worktree add <name>` creates one ({main.parent}/{main.name}--<name>,"
        " on branch ws/<name>); switch into it with EnterWorktree (its path), work"
        " and commit there, and `deckz worktree land` puts the commits on the main"
        " checkout's branch."
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


def _read_only(words: list[str]) -> bool:
    while words and re.fullmatch(r"\w+=.*", words[0]):  # VAR=value prefixes
        words = words[1:]
    if not words:
        return True
    program, args = Path(words[0]).name, words[1:]
    if program == "git":
        return _git_read_only(args)
    if program == "deckz":
        return _deckz_read_only(args)
    if program == "uv" and args[:1] == ["run"]:
        rest = args[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return bool(rest) and Path(rest[0]).name == "deckz" and _read_only(rest)
    if program == "command":
        return args[:1] in (["-v"], ["-V"])
    if program not in _READ_ONLY:
        return False
    writing = _WRITING_OPTIONS.get(program, ())
    return not any(
        arg == option
        or (option == "-i" and arg.startswith("-i"))
        or arg.startswith(f"{option}=")
        for arg in args
        for option in writing
    )


def main_checkout_denial(
    settings: "GlobalSettings", script: list[list[str]], cwd: Path
) -> str | None:
    """Why a Bash command may not run, if it changes the main checkout.

    Follows `cd` from one simple command to the next, and git's `-C`.

    Args:
        settings: The settings of the checkout the session runs in.
        script: The command's simple commands, as `agent_hooks.commands` splits them.
        cwd: The directory the command starts in.

    Returns:
        The reason, or None.
    """
    if not _required(settings):
        return None
    found = checkouts(settings.paths.git_dir)
    cwd = cwd.resolve()
    for raw in script:
        words, targets = _strip_redirections(raw, cwd)
        if into := [t for t in targets if found.in_main(t)]:
            return (
                f"This command writes {into[0]}, in the main checkout, which every"
                " agent session shares: agents change files only in a worktree of"
                " their own. " + _how_to(found.main)
            )
        if not words:
            continue
        program = Path(words[0]).name
        here = cwd
        if program == "git" and "-C" in words:
            here = _resolve(words[words.index("-C") + 1], cwd)
        touches_main = found.in_main(here) or _names_path_in(words[1:], here, found)
        if touches_main and not _read_only(words):
            shown = " ".join(words)
            shown = shown if len(shown) <= 80 else shown[:77] + "..."
            return (
                f"`{shown}` runs in the main checkout ({found.main}), or on its"
                " files, which every agent session shares: there, only read-only"
                " commands run. Run it in a worktree of your own: "
                + _how_to(found.main)
            )
        if program in {"cd", "pushd"} and len(words) > 1 and words[1] != "-":
            cwd = _resolve(words[1], cwd)
        elif program == "cd" and len(words) == 1:
            cwd = Path.home()
    return None
