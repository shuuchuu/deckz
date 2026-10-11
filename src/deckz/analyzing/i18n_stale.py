"""Compute translation staleness from git history and `Lang-sync` trailers.

No stored state (no markers, unlike the repo-side `.sync-commit` files this
replaces): a French content file or notebook is stale when a commit changed
it after the last commit that changed its English sibling, unless that
commit's `Lang-sync` trailer exempts it (`fr-only`); the English side holds
symmetrically (`en-only`). A `Lang-sync: pending` commit, or one with no
trailer, doesn't exempt anything -- it leaves the file stale until a later
commit touches the sibling, or names it in a `Lang-synced: <path>` trailer:
the pair is then in sync as of that commit, whichever side is named, which
`deckz i18n mark-synced` records in an empty commit when the changes need no
port after all (a case fix, the language's own typography). `.yml` files
aren't tracked here (see `deckz.analyzing.i18n_coverage` for their titles).

`deckz.yml`'s `i18n.synced_at` names a commit up to which every pair is
known to be in sync: it and its ancestors are ignored, so history from
before trailers were used doesn't count.
"""

import re
from collections.abc import Collection, Iterable, Iterator, Sequence
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
LANG_SYNCED = "Lang-synced"
"""The trailer naming a file whose pair is in sync as of its commit."""


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
    """The last commit before `commits` changing the sibling or marking the \
    pair in sync (`Lang-synced`), else `i18n.synced_at` if set, else None."""
    commits: tuple[CommitRef, ...]
    """The qualifying commits, oldest first."""


def _trailer_lines(message: str) -> list[tuple[str, str]]:
    """The trailers of a commit message's last paragraph, in order.

    That's its body, not the subject line.

    Returns:
        Each trailer's key and value, or `[]` if the body's last paragraph \
        isn't trailer-shaped (every line `Key: value`).
    """
    _subject, _, body = message.partition("\n")
    body = body.strip()
    if not body:
        return []
    paragraphs = re.split(r"\n\n+", body)
    lines = [line for line in paragraphs[-1].splitlines() if line.strip()]
    if not lines or not all(_TRAILER_LINE.match(line) for line in lines):
        return []
    found = []
    for line in lines:
        key, _, value = line.partition(":")
        found.append((key.strip(), value.strip()))
    return found


def _parse_trailers(message: str) -> dict[str, str]:
    return dict(_trailer_lines(message))


def lang_synced_paths(message: str) -> list[str]:
    """The paths a commit message's `Lang-synced` trailers name.

    Returns:
        Each one, repository-relative, in order.
    """
    return [value for key, value in _trailer_lines(message) if key == LANG_SYNCED]


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


@dataclass(frozen=True)
class _History:
    changes: dict[str, list[_Change]]
    """Each path's commits changing it, oldest first."""
    synced: dict[str, list[_Change]]
    """Each path's commits naming it in a `Lang-synced` trailer, oldest first."""


def _history(git_dir: Path, paths: set[str], synced_at: str | None = None) -> _History:
    """Walk the whole history once, recording every change to `paths`.

    And every commit marking one of them in sync (`Lang-synced`).

    Args:
        git_dir: Root of the repository.
        paths: Repository-relative paths to record the changes of.
        synced_at: A revision whose commit and ancestors are skipped, or None.

    Returns:
        What happened to each path.

    Raises:
        InvalidConfigurationError: If `synced_at` names no commit.
    """
    from pygit2 import Commit, Repository
    from pygit2.enums import SortMode

    history = _History(
        changes={path: [] for path in paths}, synced={path: [] for path in paths}
    )
    repo = Repository(str(git_dir))
    if repo.is_empty or repo.head_is_unborn:
        return history
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
        synced = set(lang_synced_paths(commit.message)) & paths
        if not relevant and not synced:
            continue
        change = _Change(
            sha=str(commit.id),
            subject=commit.message.partition("\n")[0],
            ordinal=ordinal,
            lang_sync=lang_sync_kind(commit.message),
        )
        for path in relevant:
            history.changes[path].append(change)
        for path in synced:
            history.synced[path].append(change)
    return history


def _pair_staleness(
    a: PurePosixPath,
    b: PurePosixPath,
    history: _History,
    synced_at: str | None = None,
) -> Iterator[StaleFile]:
    # Marking either side in sync settles the pair, both ways.
    synced = [*history.synced.get(str(a), []), *history.synced.get(str(b), [])]
    for path, sibling, exempt in ((a, b, "fr-only"), (b, a, "en-only")):
        baseline = max(
            [*history.changes.get(str(sibling), []), *synced],
            key=lambda change: change.ordinal,
            default=None,
        )
        qualifying = [
            change
            for change in history.changes.get(str(path), [])
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
    pairs = lang_pairs(settings)
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
    history = _history(git_dir, paths, synced_at)

    stale = [
        finding
        for a, b in pairs
        for finding in _pair_staleness(a, b, history, synced_at)
    ]
    return sorted(stale, key=lambda finding: finding.path)


def mark_synced(
    settings: "GlobalSettings", paths: Sequence[Path], reason: str
) -> tuple[str, list[StaleFile]]:
    """Record that what `deckz i18n stale` lists for `paths` needs no port.

    For changes found to need nothing in the other language after they were
    committed (a case fix, the language's own typography), when no commit is
    left to give a `Lang-sync: fr-only` trailer: an empty commit naming each
    file in a `Lang-synced` trailer, with `reason` in its body, after which
    each one's pair counts as in sync. It commits nothing else, whatever is
    staged.

    Args:
        settings: The repository's settings.
        paths: Files listed by `deckz i18n stale` (either side of the pair), \
            absolute or relative to the current directory.
        reason: Why nothing needs porting.

    Returns:
        The commit's sha, and the entries it settled.

    Raises:
        DeckzError: If `reason` is empty, a path isn't in `deckz i18n stale` \
            or git refuses the commit.
    """
    from subprocess import run

    reason = reason.strip()
    if not reason:
        msg = 'say why nothing needs porting: --reason "<why>"'
        raise DeckzError(msg)
    git_dir = settings.paths.git_dir.resolve()
    relative = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(git_dir):
            msg = f"{path}: not in the repository ({git_dir})"
            raise DeckzError(msg)
        relative.append(PurePosixPath(resolved.relative_to(git_dir).as_posix()))
    stale = stale_files(settings, paths)
    settled = [
        finding
        for finding in stale
        if finding.path in relative or finding.sibling in relative
    ]
    listed = {finding.path for finding in stale} | {f.sibling for f in stale}
    for path in relative:
        if path not in listed:
            msg = (
                f"{path}: nothing waits for a port (`deckz i18n stale` doesn't "
                "list it nor its sibling)"
            )
            raise DeckzError(msg)
    subject = (
        f"Nothing to port from {relative[0]}"
        if len(relative) == 1
        else f"Nothing to port from {len(relative)} files"
    )
    trailers = "\n".join(f"{LANG_SYNCED}: {path}" for path in relative)
    message = f"{subject}\n\n{reason}\n\n{trailers}\n"
    # `--only` with no path commits none of what's staged. `--no-verify`: the
    # commit changes no file, so the pre-commit hook would only check HEAD's
    # tree again (seconds, and failing on problems that aren't this commit's),
    # and the commit-msg hook's rule is about files changed.
    result = run(
        [
            "git",
            "commit",
            "--allow-empty",
            "--only",
            "--no-verify",
            "--cleanup=whitespace",
            "--file=-",
        ],
        cwd=git_dir,
        input=message,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        msg = f"git commit: {(result.stderr or result.stdout).strip()}"
        raise DeckzError(msg)
    sha = run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha, settled


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


def lang_pairs(
    settings: "GlobalSettings",
) -> list[tuple[PurePosixPath, PurePosixPath]]:
    """Every fr/en pair the `Lang-sync` rule covers: content files and notebooks.

    Slow on a large repository (finding the decks' own content directories:
    about a second for 80 decks); a caller checking several sets of paths
    computes them once.

    Returns:
        Each pair, French side first.
    """
    return [*content_pairs(settings), *notebook_pairs(settings)]


def one_sided(
    changed: Collection[str],
    pairs: Iterable[tuple[PurePosixPath, PurePosixPath]],
) -> list[OneSidedChange]:
    """The pairs with exactly one side among `changed`: the `Lang-sync` rule.

    A commit changing such a pair needs a `Lang-sync` trailer (the commit-msg
    hook, `deckz hooks check-commits`).

    Args:
        changed: Changed paths, relative to the repository's root.
        pairs: The pairs (`lang_pairs`).

    Returns:
        Each of them, with its side changed.
    """
    return [
        OneSidedChange(fr, en, "fr" if str(fr) in changed else "en")
        for fr, en in pairs
        if (str(fr) in changed) != (str(en) in changed)
    ]


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
    return one_sided(
        {path for path in staged.split("\0") if path}, lang_pairs(settings)
    )


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

    pairs = lang_pairs(settings)
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
        changes = tuple(one_sided(changed, pairs))
        if changes:
            found.append(OneSidedCommit(sha, message.splitlines()[0], changes))
    return found
