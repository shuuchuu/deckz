"""Compute translation staleness from git history and `Lang-sync` trailers.

No stored state (no markers, unlike the repo-side `.sync-commit` files this
replaces): a French content file or notebook is stale when a commit changed
it after the last commit that changed its English sibling, unless that
commit's `Lang-sync` trailer exempts it (`fr-only`); the English side holds
symmetrically (`en-only`). A `Lang-sync: pending` commit, or one with no
trailer, doesn't exempt anything -- it leaves the file stale until a later
commit touches the sibling. `.yml` files aren't tracked here (see
`deckz.analyzing.i18n_coverage` for their titles).

`deckz.yml`'s `i18n.synced_at` names a commit up to which every pair is
known to be in sync: it and its ancestors are ignored, so history from
before trailers were used doesn't count.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..exceptions import DeckzError, InvalidConfigurationError
from ..utils import content_dirs

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
"""git's well-known empty tree object, to diff a file against nothing."""

_TRAILER_LINE = re.compile(r"^[A-Za-z][\w-]*:\s?.*$")
_LANG_SYNC_KIND = re.compile(r"^(fr-only|en-only|pending)\b")


@dataclass(frozen=True)
class _Change:
    sha: str
    subject: str
    ordinal: int
    lang_sync: str | None


@dataclass(frozen=True)
class CommitRef:
    sha: str
    subject: str


@dataclass(frozen=True)
class StaleFile:
    """A file with commits that may not be ported to `sibling` yet."""

    path: PurePosixPath
    sibling: PurePosixPath
    since: str | None
    """The sibling's last commit sha before `commits`, else `i18n.synced_at` \
    if set, else None (the sibling was never touched)."""
    commits: tuple[CommitRef, ...]
    """The qualifying commits, oldest first."""


def _parse_trailers(message: str) -> dict[str, str]:
    """The trailers of a commit message's last paragraph.

    That's its body, not the subject line.

    Returns:
        Each trailer key mapped to its value, or `{}` if the body's last \
        paragraph isn't trailer-shaped (every line `Key: value`).
    """
    _subject, _, body = message.partition("\n")
    body = body.strip()
    if not body:
        return {}
    paragraphs = re.split(r"\n\n+", body)
    lines = [line for line in paragraphs[-1].splitlines() if line.strip()]
    if not lines or not all(_TRAILER_LINE.match(line) for line in lines):
        return {}
    trailers = {}
    for line in lines:
        key, _, value = line.partition(":")
        trailers[key.strip()] = value.strip()
    return trailers


def lang_sync_kind(message: str) -> str | None:
    value = _parse_trailers(message).get("Lang-sync")
    if not value:
        return None
    match = _LANG_SYNC_KIND.match(value)
    return match.group(1) if match else None


def _en_sibling(path: PurePosixPath) -> PurePosixPath:
    return path.parent / "en" / path.name


def _notebook_sibling(path: PurePosixPath) -> PurePosixPath | None:
    for lang, other in (("fr", "en"), ("en", "fr")):
        suffix = f"-{lang}.ipynb"
        if path.name.endswith(suffix):
            return path.with_name(path.name.removesuffix(suffix) + f"-{other}.ipynb")
    return None


def content_pairs(
    settings: "GlobalSettings",
) -> Iterator[tuple[PurePosixPath, PurePosixPath]]:
    git_dir = settings.paths.git_dir
    for content_dir in content_dirs(git_dir, settings.paths.content_dir):
        if not content_dir.is_dir():
            continue
        for path in content_dir.rglob("*.md"):
            rel = PurePosixPath(path.relative_to(git_dir).as_posix())
            if "en" in rel.parts:
                continue
            yield rel, _en_sibling(rel)


def notebook_pairs(
    settings: "GlobalSettings",
) -> Iterator[tuple[PurePosixPath, PurePosixPath]]:
    git_dir = settings.paths.git_dir
    notebooks_dir = settings.paths.labs_notebooks_dir
    if not notebooks_dir.is_dir():
        return
    seen: set[PurePosixPath] = set()
    for path in notebooks_dir.rglob("*.ipynb"):
        rel = PurePosixPath(path.relative_to(git_dir).as_posix())
        sibling = _notebook_sibling(rel)
        if sibling is None:
            continue
        fr = rel if rel.name.endswith("-fr.ipynb") else sibling
        if fr in seen:
            continue
        seen.add(fr)
        en = _notebook_sibling(fr)
        if en is not None:
            yield fr, en


def _changes_by_path(
    git_dir: Path, paths: set[str], synced_at: str | None = None
) -> dict[str, list[_Change]]:
    """Walk the whole history once, recording every change to `paths`.

    Args:
        git_dir: Root of the repository.
        paths: Repository-relative paths to record the changes of.
        synced_at: A revision whose commit and ancestors are skipped, or None.

    Returns:
        Each path mapped to its changes, oldest first.

    Raises:
        InvalidConfigurationError: If `synced_at` names no commit.
    """
    from pygit2 import Commit, Repository
    from pygit2.enums import SortMode

    changes: dict[str, list[_Change]] = {path: [] for path in paths}
    repo = Repository(str(git_dir))
    if repo.is_empty or repo.head_is_unborn:
        return changes
    walker = repo.walk(repo.head.target, SortMode.TOPOLOGICAL | SortMode.REVERSE)
    if synced_at is not None:
        try:
            synced = repo.revparse_single(synced_at).peel(Commit)
        except (KeyError, ValueError) as error:
            msg = f"i18n.synced_at: {synced_at!r} is no commit of {git_dir}"
            raise InvalidConfigurationError(msg) from error
        walker.hide(synced.id)
    for ordinal, commit in enumerate(walker):
        if len(commit.parents) > 1:
            continue  # Merge commits: no diff attributed, as `git log` does by default.
        diff = (
            commit.parents[0].tree.diff_to_tree(commit.tree)
            if commit.parents
            else commit.tree.diff_to_tree(swap=True)
        )
        touched = {delta.new_file.path or delta.old_file.path for delta in diff.deltas}
        relevant = touched & paths
        if not relevant:
            continue
        change = _Change(
            sha=str(commit.id),
            subject=commit.message.partition("\n")[0],
            ordinal=ordinal,
            lang_sync=lang_sync_kind(commit.message),
        )
        for path in relevant:
            changes[path].append(change)
    return changes


def _pair_staleness(
    a: PurePosixPath,
    b: PurePosixPath,
    changes: dict[str, list[_Change]],
    synced_at: str | None = None,
) -> Iterator[StaleFile]:
    for path, sibling, exempt in ((a, b, "fr-only"), (b, a, "en-only")):
        sibling_events = changes.get(str(sibling), [])
        baseline = sibling_events[-1] if sibling_events else None
        qualifying = [
            change
            for change in changes.get(str(path), [])
            if (baseline is None or change.ordinal > baseline.ordinal)
            and change.lang_sync != exempt
        ]
        if qualifying:
            yield StaleFile(
                path=path,
                sibling=sibling,
                since=baseline.sha if baseline else synced_at,
                commits=tuple(
                    CommitRef(change.sha, change.subject) for change in qualifying
                ),
            )


def stale_files(
    settings: "GlobalSettings", targets: Sequence[Path] = ()
) -> list[StaleFile]:
    """Every content file or notebook with unported changes relative to its sibling.

    Args:
        settings: The repository's settings.
        targets: Restrict to the pairs with a path under one of these \
            files or directories, or every pair in the repository if empty.

    Returns:
        One entry per stale side of a pair, sorted by path.
    """
    git_dir = settings.paths.git_dir
    pairs = [*content_pairs(settings), *notebook_pairs(settings)]
    if targets:
        resolved = [target.resolve() for target in targets]
        pairs = [
            (a, b)
            for a, b in pairs
            if any(
                (git_dir / a).is_relative_to(root) or (git_dir / b).is_relative_to(root)
                for root in resolved
            )
        ]
    paths = {str(path) for pair in pairs for path in pair}
    synced_at = settings.i18n.synced_at
    changes = _changes_by_path(git_dir, paths, synced_at)

    stale = [
        finding
        for a, b in pairs
        for finding in _pair_staleness(a, b, changes, synced_at)
    ]
    return sorted(stale, key=lambda finding: finding.path)


@dataclass(frozen=True)
class OneSidedChange:
    """A fr/en pair whose staged changes touch one side only."""

    fr: PurePosixPath
    en: PurePosixPath
    changed: str
    """The side changed: `fr` or `en`."""

    @property
    def changed_path(self) -> PurePosixPath:
        return self.fr if self.changed == "fr" else self.en

    @property
    def other_path(self) -> PurePosixPath:
        return self.en if self.changed == "fr" else self.fr


def staged_one_sided_pairs(settings: "GlobalSettings") -> list[OneSidedChange]:
    """Every fr/en pair with exactly one side in the git index's staged changes.

    Used by the `commit-msg` hook (`deckz hooks check-commit-msg`): unlike
    `stale_files`, which looks at the whole history, this only looks at
    what's about to be committed, to ask for a `Lang-sync` trailer right
    when it's needed.

    Args:
        settings: The repository's settings.

    Returns:
        Every pair where the staged changes touch one side but not the other.
    """
    from subprocess import run

    git_dir = settings.paths.git_dir
    staged = run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=git_dir,
        capture_output=True,
        check=True,
    ).stdout.decode()
    staged_paths = {path for path in staged.split("\0") if path}
    pairs = [*content_pairs(settings), *notebook_pairs(settings)]
    return [
        OneSidedChange(fr, en, "fr" if str(fr) in staged_paths else "en")
        for fr, en in pairs
        if (str(fr) in staged_paths) != (str(en) in staged_paths)
    ]


@dataclass(frozen=True)
class OneSidedCommit:
    """A commit changing one side of fr/en pairs with no `Lang-sync` trailer."""

    sha: str
    subject: str
    changes: tuple[OneSidedChange, ...]


def one_sided_commits(
    settings: "GlobalSettings", revisions: str
) -> list[OneSidedCommit]:
    """The commits of `revisions` the commit-msg hook would have refused.

    For CI, where a contributor's commits arrive whether or not they
    installed the hooks: each commit touching one side of a pair (as the
    pairs stand now) without a `Lang-sync` trailer. A `revisions` git can't
    list raises a `DeckzError` naming git's error.

    Args:
        settings: The repository's settings.
        revisions: A git revision range, e.g. `origin/main..HEAD`.

    Returns:
        The offending commits, oldest first.
    """
    from subprocess import run

    git_dir = settings.paths.git_dir

    def git(*args: str) -> str:
        result = run(
            ["git", *args], cwd=git_dir, capture_output=True, text=True, check=False
        )
        if result.returncode:
            msg = f"git {' '.join(args)}: {result.stderr.strip()}"
            raise DeckzError(msg)
        return result.stdout

    pairs = [*content_pairs(settings), *notebook_pairs(settings)]
    found = []
    for sha in git("rev-list", "--reverse", "--no-merges", revisions).split():
        message = git("show", "-s", "--format=%B", sha)
        if lang_sync_kind(message) is not None:
            continue
        changed = set(
            git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha).split(
                "\0"
            )
        )
        changes = tuple(
            OneSidedChange(fr, en, "fr" if str(fr) in changed else "en")
            for fr, en in pairs
            if (str(fr) in changed) != (str(en) in changed)
        )
        if changes:
            found.append(OneSidedCommit(sha, message.splitlines()[0], changes))
    return found
