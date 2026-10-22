"""Demos whose code changed after their outputs were written: `deckz labs stale`.

A demo stores the outputs of a full run (`deckz labs outputs`), and an edit to
its code cells after that can leave them showing what the code no longer does.
Like translation staleness, that's a fact about history, recomputed from it:
each state of the demo's file (every commit changing it, then the working
tree) has a code digest (its code cells, blank and comment-only lines left
out) and an outputs digest. Its outputs were *written* at the last state whose
outputs differ from the state before it, or are current as of the last commit
naming it in a `Lab-outputs-current: <path>` trailer (`deckz labs
mark-current`, when a change needs no rerun), whichever is later. The demo is
stale when its code now differs from its code then.

Nothing is stored but a cache of each blob's digests, by blob id
(`<git_dir>/.run/lab-outputs.json`): a demo can weigh megabytes, and every
state of every demo would otherwise be parsed on each run.
"""

import functools
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from ..commits import commit_empty, trailer_values
from ..exceptions import DeckzError
from .comparison import variants
from .notebook import cell_source

if TYPE_CHECKING:
    from pygit2 import Repository

    from ..configuring.settings import GlobalSettings


LAB_OUTPUTS_CURRENT = "Lab-outputs-current"
"""The trailer naming a demo whose outputs are current as of its commit."""

_DEMO = "demo"
_WORKING_TREE = sys.maxsize
"""The working tree's ordinal: after every commit, marking ones included."""


@dataclass(frozen=True)
class OutputsCommit:
    sha: str
    subject: str


@dataclass(frozen=True)
class StaleDemo:
    """A demo whose code changed since its outputs were written."""

    path: PurePosixPath
    """Repository-relative."""
    since: str
    """The commit its outputs were written in, or marked current by."""
    commits: tuple[OutputsCommit, ...]
    """The commits changing its code since, oldest first."""
    uncommitted: bool
    """Whether the working tree changes its code too."""


@dataclass(frozen=True)
class _Digests:
    code: str
    outputs: str
    has_outputs: bool


@dataclass(frozen=True)
class _State:
    ordinal: int
    commit: OutputsCommit | None
    """None for the working tree."""
    blob: str | None
    """None when the state deletes the file."""


def _digests(data: bytes) -> _Digests | None:
    try:
        notebook = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    cells = [
        cell
        for cell in notebook.get("cells", [])
        if isinstance(cell, dict) and cell.get("cell_type") == "code"
    ]
    code = [
        [
            line.rstrip()
            for line in cell_source(cell).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        for cell in cells
    ]
    outputs = [
        (cell.get("outputs") or [], cell.get("execution_count")) for cell in cells
    ]
    return _Digests(
        code=sha256(json.dumps(code).encode()).hexdigest(),
        outputs=sha256(json.dumps(outputs, sort_keys=True).encode()).hexdigest(),
        has_outputs=any(cell_outputs for cell_outputs, _ in outputs),
    )


class _Cache:
    """Each blob's digests, by blob id, kept across runs under `.run/`."""

    def __init__(self, path: Path, repo: "Repository") -> None:
        self._path = path
        self._repo = repo
        try:
            self._entries: dict[str, Any] = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            self._entries = {}
        self._changed = False

    def get(
        self, blob: str, read: Callable[[], bytes] | None = None
    ) -> _Digests | None:
        if (entry := self._entries.get(blob)) is not None:
            return _Digests(*entry) if entry else None
        data = read() if read is not None else self._repo[blob].read_raw()
        digests = _digests(data)
        self._entries[blob] = (
            [digests.code, digests.outputs, digests.has_outputs] if digests else []
        )
        self._changed = True
        return digests

    def save(self) -> None:
        if not self._changed:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f"{self._path.name}.{os.getpid()}")
        temporary.write_text(json.dumps(self._entries), encoding="utf-8")
        temporary.replace(self._path)  # Atomic: another deckz may read it.


def demo_paths(settings: "GlobalSettings") -> list[PurePosixPath]:
    """Every demo notebook (`<lab>/demo-<lang>.ipynb`), repository-relative.

    Returns:
        Their paths, sorted.
    """
    notebooks_dir = settings.paths.labs_notebooks_dir
    if not notebooks_dir.is_dir():
        return []
    git_dir = settings.paths.git_dir
    return sorted(
        PurePosixPath(
            (stem.parent / f"{stem.name}-{lang}.ipynb").relative_to(git_dir).as_posix()
        )
        for stem, langs in variants(notebooks_dir).items()
        if stem.name == _DEMO
        for lang in langs
    )


def _git(git_dir: Path, *args: str) -> str:
    from subprocess import run

    result = run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=git_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _histories(
    git_dir: Path, notebooks_dir: Path, paths: set[str]
) -> tuple[dict[str, list[_State]], dict[str, list[tuple[int, OutputsCommit]]]]:
    # Every commit changing one of `paths` (its blob there), and every commit
    # naming one in a trailer, oldest first. git's own log, limited to the
    # notebooks directory, takes milliseconds where diffing each commit's
    # whole tree in pygit2 took seconds.
    states: dict[str, list[_State]] = {path: [] for path in paths}
    marks: dict[str, list[tuple[int, OutputsCommit]]] = {path: [] for path in paths}
    order = _git(git_dir, "rev-list", "--topo-order", "--reverse", "HEAD").split()
    ordinals = {sha: ordinal for ordinal, sha in enumerate(order)}
    where = notebooks_dir.relative_to(git_dir).as_posix()
    log = _git(
        git_dir,
        "log",
        "--no-merges",  # No diff attributed to merges, as `git log` does by default.
        "--topo-order",
        "--reverse",
        "--raw",
        "--no-abbrev",
        "--no-renames",
        "--format=%x00%H%x00%s",
        "--",
        where,
    )
    fields = log.split("\0")[1:]
    for sha, rest in zip(fields[::2], fields[1::2], strict=True):
        subject, *lines = rest.split("\n")
        ref = OutputsCommit(sha, subject)
        for line in lines:
            if not line.startswith(":"):
                continue
            info, _, path = line.partition("\t")
            if path in states:
                _, _, _, blob, status = info.split()
                states[path].append(
                    _State(ordinals[sha], ref, None if status == "D" else blob)
                )
    marking = _git(
        git_dir,
        "log",
        "--fixed-strings",
        f"--grep={LAB_OUTPUTS_CURRENT}:",
        "--format=%x00%H%x00%B",
    )
    fields = marking.split("\0")[1:]
    for sha, message in zip(fields[::2], fields[1::2], strict=True):
        ref = OutputsCommit(sha, message.partition("\n")[0])
        for path in set(trailer_values(message, LAB_OUTPUTS_CURRENT)) & paths:
            marks[path].append((ordinals[sha], ref))
    for found in marks.values():
        found.sort(key=lambda mark: mark[0])
    return states, marks


def _uncommitted(git_dir: Path, notebooks_dir: Path) -> set[str]:
    # The notebooks the working tree changes: hashing every demo is a second.
    where = notebooks_dir.relative_to(git_dir).as_posix()
    status = _git(
        git_dir, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", where
    )
    entries = status.split("\0")
    found = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        found.add(entry[3:])
        if entry[0] in "RC":  # A rename's or copy's source follows.
            index += 1
    return found


def _staleness(
    path: str,
    states: list[_State],
    marks: list[tuple[int, OutputsCommit]],
    digests: Callable[[int], _Digests | None],
) -> StaleDemo | None:
    # `digests(index)` parses a state: from now back to the outputs' last
    # change only, a couple of states for most demos.
    now = digests(len(states) - 1) if states else None
    if now is None or not now.has_outputs:
        return None  # Never run, or not a notebook: `lab-outputs` says so.
    written = None
    for index in range(len(states) - 1, -1, -1):
        found = digests(index)
        before = digests(index - 1) if index else None  # Deleted, or not JSON: None.
        if (
            found is not None
            and found.has_outputs
            and (before is None or before.outputs != found.outputs)
        ):
            written = index
            break
    if written is None:
        return None
    baseline, since = written, states[written].commit
    if marks and marks[-1][0] > states[written].ordinal:
        ordinal, since = marks[-1]
        baseline = max(i for i, state in enumerate(states) if state.ordinal <= ordinal)
    reference = digests(baseline)
    if since is None or reference is None or reference.code == now.code:
        return None  # Written in the working tree, or no code change since.
    changing = [
        state
        for index, state in enumerate(states)
        if index > baseline
        and (current := digests(index)) is not None
        and (previous := digests(index - 1)) is not None
        and current.code != previous.code
    ]
    return StaleDemo(
        path=PurePosixPath(path),
        since=since.sha,
        commits=tuple(state.commit for state in changing if state.commit),
        uncommitted=any(state.commit is None for state in changing),
    )


def _parser(
    cache: _Cache, history: list[_State], file: Path
) -> Callable[[int], _Digests | None]:
    @functools.cache
    def digests(index: int) -> _Digests | None:
        state = history[index]
        if state.blob is None:
            return None
        return cache.get(state.blob, file.read_bytes if state.commit is None else None)

    return digests


def stale_demos(
    settings: "GlobalSettings", targets: Sequence[Path] = ()
) -> list[StaleDemo]:
    """Every demo whose code changed since its outputs were written.

    Args:
        settings: The repository's settings.
        targets: Restrict to the demos under one of these files or \
            directories, or every demo if empty.

    Returns:
        One entry per stale demo, sorted by path.
    """
    from pygit2 import Repository, hashfile

    git_dir = settings.paths.git_dir
    paths = demo_paths(settings)
    if targets:
        roots = [target.resolve() for target in targets]
        paths = [
            path
            for path in paths
            if any((git_dir / path).resolve().is_relative_to(root) for root in roots)
        ]
    if not paths:
        return []
    notebooks_dir = settings.paths.labs_notebooks_dir
    states, marks = _histories(git_dir, notebooks_dir, {str(path) for path in paths})
    uncommitted = _uncommitted(git_dir, notebooks_dir)
    repo = Repository(str(git_dir))
    cache = _Cache(settings.paths.git_dir / ".run" / "lab-outputs.json", repo)
    stale = []
    for path in paths:
        history = list(states[str(path)])
        file = git_dir / path  # On disk: `demo_paths` found it there.
        if str(path) in uncommitted or not history:
            blob = str(hashfile(str(file)))
            if not history or history[-1].blob != blob:
                history.append(_State(_WORKING_TREE, None, blob))
        digests = _parser(cache, history, file)
        if found := _staleness(str(path), history, marks[str(path)], digests):
            stale.append(found)
    cache.save()
    return stale


def mark_current(
    settings: "GlobalSettings", paths: Sequence[Path], reason: str
) -> tuple[str, list[StaleDemo]]:
    """Record that the outputs `deckz labs stale` lists for `paths` are current.

    For code changes found to change no output that matters (a comment, a
    download line, a sweeping rename): an empty commit naming each demo in a
    `Lab-outputs-current` trailer, with `reason` in its body. It commits
    nothing else, whatever is staged.

    Args:
        settings: The repository's settings.
        paths: Demos `deckz labs stale` lists, absolute or relative to the \
            current directory.
        reason: Why their outputs need no rerun.

    Returns:
        The commit's sha, and the entries it settled.

    Raises:
        DeckzError: If `reason` is empty, a path isn't in `deckz labs stale`, \
            its working tree changes its code, or git refuses the commit.
    """
    reason = reason.strip()
    if not reason:
        msg = 'say why the outputs need no rerun: --reason "<why>"'
        raise DeckzError(msg)
    git_dir = settings.paths.git_dir.resolve()
    relative = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(git_dir):
            msg = f"{path}: not in the repository ({git_dir})"
            raise DeckzError(msg)
        relative.append(PurePosixPath(resolved.relative_to(git_dir).as_posix()))
    stale = {demo.path: demo for demo in stale_demos(settings, paths)}
    for path in relative:
        if path not in stale:
            msg = (
                f"{path}: its outputs are current (`deckz labs stale` doesn't list it)"
            )
            raise DeckzError(msg)
        if stale[path].uncommitted:
            msg = (
                f"{path}: the working tree changes its code: commit it first, then"
                " mark it (or add the trailer to that commit)"
            )
            raise DeckzError(msg)
    subject = (
        f"Keep the outputs of {relative[0]}"
        if len(relative) == 1
        else f"Keep the outputs of {len(relative)} demos"
    )
    trailers = "\n".join(f"{LAB_OUTPUTS_CURRENT}: {path}" for path in relative)
    sha = commit_empty(git_dir, f"{subject}\n\n{reason}\n\n{trailers}\n")
    return sha, [stale[path] for path in relative]
