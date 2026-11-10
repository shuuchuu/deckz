"""The review registry: which version of each file was reviewed, `deckz review`.

A *report* is any Markdown file under `deckz.yml`'s `review.dir`, at any
depth. Its YAML front matter's `reviewed` key, which deckz owns, records the
files the report reviewed, each with the git blob sha (`git hash-object`) of
the version reviewed, plus the date and the commit (`base`) of the last
mark:

```yaml
---
reviewed:
  date: 2026-10-23
  base: <HEAD when last marked>
  files:
    content/intro.md: <blob sha of the reviewed version>
---
```

A blob sha names a content, not a commit: it survives rebases, and the
diff from it to the working tree is exactly what changed since the review.
deckz reads and rewrites only that key: the rest of the front matter and
the report's body are the repository's, kept byte for byte.

A file marked on another day or commit than the report's (a mark naming only
some of the report's files leaves the others' day as it was; `mark --at`
registers files at a past commit) has its own day and commit:

```yaml
    content/older.md:
      blob: <blob sha>
      date: 2026-10-01
      base: <HEAD when it was marked>
```

A file is *fresh* when its working-tree version is the one recorded, *stale*
when it differs, *unreviewed* when no report records it (and *deleted* when
a report records a file that is gone). A file several reports record takes
the most recent mark: by its date, then by its base's commit time. A fresh
file is *due* when a rule of `review.rules` covering it took effect after
its mark: reviewed at its version, but not against that rule (a stale file
lists the rules it is due for too).

`mark` refuses, at the point of harm, to record a file whose change since
its review came from elsewhere: another session's or person's commits that
reached this branch through the main branch (`changed_elsewhere`), since
nobody reviewed them. Which notebooks or other files a content file goes
with is the repository's own convention: a report records whatever it is
given, and `status` lists, next to a deck's content files, the other files
the reports covering them record.

A report's *kind* comes from its path, so that a script finds a report
without reading it (`report_kind`): `<review.dir>/<deck directory>.md` is
that deck's report (its deck pass), anything under `<review.dir>/sections/`
a shared section's report, and any other path is misplaced (the
`review-headers` check). A deck report records the deck's own files
(`deck_own_files`): its pass holds while they are fresh, and changes to the
shared sections it includes show at the content level, in the section
reports, not in it. A report under `<review.dir>/<course notes directory>/`
(the course notes directory's path relative to the repository, e.g.
`docs/qa/course-notes/python/basics.md`) reviews course notes chapters.
"""

import re
import subprocess
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher, unified_diff
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from ..exceptions import ReviewError

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings, ReviewRule
    from ..models import Deck, ParsedDeck

State = Literal["fresh", "due", "stale", "unreviewed", "deleted"]
Kind = Literal["section", "deck", "course-notes"]

SECTIONS_DIR = "sections"
"""The subdirectory of `review.dir` that holds the shared sections' reports."""

_SHA = re.compile(r"[0-9a-f]{40}")
_KEY = "reviewed"
_FENCE = "---"


@dataclass(frozen=True)
class Mark:
    """One report's record of one file."""

    report: str
    """The report, relative to the repository."""
    date: date
    base: str
    blob: str
    """The blob sha of the version reviewed."""


@dataclass(frozen=True)
class Report:
    path: str
    """Relative to the repository."""
    date: date | None
    base: str | None
    files: Mapping[str, str]
    """Path relative to the repository to the blob sha reviewed, sorted."""
    own: Mapping[str, tuple[date, str]] = field(default_factory=dict)
    """The files marked on another day or commit than the report's, with \
    that day and commit."""


@dataclass(frozen=True)
class FileReview:
    path: str
    """Relative to the repository."""
    state: State
    marks: tuple[Mark, ...] = ()
    """Every report recording it, the most recent mark first (the one used)."""
    added: int | None = None
    """Stale: lines added since the review; None if the reviewed version \
    isn't in the repository's objects."""
    removed: int | None = None
    frames: int | None = None
    """A content file's frames (`# ` headings outside code blocks)."""
    changed_frames: int | None = None
    """Stale content file: the frames its changes since the review touch, in \
    the reviewed or the current version, whichever has more; None if the \
    reviewed version isn't in the repository's objects."""
    due: tuple["ReviewRule", ...] = ()
    """The rules (`review.rules`) covering it that took effect after its \
    mark: its state is `due` if it's at the version reviewed."""

    @property
    def report(self) -> str | None:
        """The report whose mark is used, None if unreviewed."""
        return self.marks[0].report if self.marks else None


@dataclass(frozen=True)
class SectionReview:
    section: str
    """The section's path relative to the shared content directory."""
    files: tuple[FileReview, ...]


@dataclass(frozen=True)
class DeckReview:
    deck: str
    """The deck's directory, relative to the repository."""
    sections: tuple[SectionReview, ...]
    """Its content files, by the innermost section including them (a \
    deck-level file include: its directory), in the deck's order."""
    others: tuple[FileReview, ...]
    """The files other than content files the reports covering the deck's \
    content files record (e.g. lab notebooks), its pass's files left out."""
    deck_pass: "DeckPass"
    chapters: tuple[FileReview, ...] = ()
    """Its course notes' French chapters that are written, in its order."""

    @property
    def content(self) -> tuple[FileReview, ...]:
        """Its content files, every section's."""
        return tuple(review for section in self.sections for review in section.files)

    @property
    def frames(self) -> int:
        """Its content files' frames to review, counted as `RankedSection.frames`."""
        return sum(_frames_to_review(review) for review in self.content)


@dataclass(frozen=True)
class DeckPass:
    """A deck's pass: its report (`deck_report_path`) and its own files."""

    report: str
    """Where the deck's report is, or goes, relative to the repository."""
    date: date | None
    """Of its last mark; None when no pass is recorded."""
    base: str | None
    files: tuple[FileReview, ...]
    """The deck's own files (`deck_own_files`) and any other file the \
    report records, against the report's marks alone."""

    @property
    def holds(self) -> bool:
        """Whether a pass is recorded and every file is at the version it read."""
        return self.date is not None and all(f.state == "fresh" for f in self.files)


@dataclass(frozen=True)
class RankedSection:
    section: str
    """A shared section's path relative to the shared content directory."""
    decks: int
    """How many decks include at least one of its files."""
    files: tuple[FileReview, ...]
    """Its files some deck includes."""
    score: int
    """`decks` times its `frames` to review."""

    def count(self, state: State) -> int:
        """How many of its files are in `state`.

        Returns:
            The count.
        """
        return sum(review.state == state for review in self.files)

    @property
    def frames(self) -> int:
        """The frames to review: all its unreviewed files', its stale ones' changed."""
        return sum(_frames_to_review(review) for review in self.files)

    @property
    def reports(self) -> tuple[str, ...]:
        """The reports recording one of its files."""
        return tuple(
            sorted({mark.report for review in self.files for mark in review.marks})
        )


@dataclass(frozen=True)
class FileDiff:
    path: str
    state: State
    """`stale` or `deleted`: a fresh file has no diff."""
    blob: str
    """The version reviewed."""
    added: int | None
    removed: int | None
    diff: str | None
    """Unified diff from the reviewed version to the working tree; None if \
    deleted, or if the reviewed version isn't in the repository's objects."""


@dataclass(frozen=True)
class MarkResult:
    report: str
    created: bool
    added: tuple[str, ...] = ()
    refreshed: tuple[str, ...] = ()
    """Recorded again, at their new version."""
    unchanged: tuple[str, ...] = ()
    """Already recorded at their current version."""
    forgotten: tuple[str, ...] = ()
    refused: tuple[tuple[str, str], ...] = ()
    """Each refused path, with why and how to proceed."""
    not_recorded: tuple[str, ...] = field(default=())
    """Paths given to `--forget` that the report doesn't record."""


########################################################################################
# Settings and paths                                                                   #
########################################################################################


def review_dir(settings: "GlobalSettings") -> Path:
    """The directory of the reports.

    Returns:
        Its absolute path.

    Raises:
        ReviewError: If `review.dir` isn't set.
    """
    if settings.review.dir is None:
        msg = (
            "no review reports directory: set `review.dir` in deckz.yml, e.g. "
            "`review: {dir: docs/qa}`"
        )
        raise ReviewError(msg)
    return settings.paths.git_dir / settings.review.dir


def _rel(settings: "GlobalSettings", path: Path) -> str:
    return path.relative_to(settings.paths.git_dir).as_posix()


def report_kind(
    settings: "GlobalSettings", path: Path
) -> tuple[Kind, str | None] | None:
    """A report's kind, from its path under `review.dir`.

    `<review.dir>/<deck directory>.md`, the deck's directory relative to the
    repository, is that deck's report; a Markdown file under
    `<review.dir>/sections/` a shared section's report; one under
    `<review.dir>/<course notes directory>/` (its path relative to the
    repository) a report on course notes chapters.

    Args:
        settings: The repository's settings.
        path: The report, absolute, under `review.dir`.

    Returns:
        Its kind and, for a deck's report, the deck's directory relative to \
        the repository; None if it is none of them.
    """
    relative = PurePosixPath(path.relative_to(review_dir(settings)).as_posix())
    if relative.suffix != ".md":
        return None
    deck = relative.with_suffix("")
    if (settings.paths.git_dir / deck / "deck.yml").is_file():
        return "deck", deck.as_posix()
    if len(relative.parts) > 1 and relative.parts[0] == SECTIONS_DIR:
        return "section", None
    notes = course_notes_reports_dir(settings)
    if notes is not None and relative.is_relative_to(notes) and relative != notes:
        return "course-notes", None
    return None


def course_notes_reports_dir(settings: "GlobalSettings") -> PurePosixPath | None:
    """Where the course notes' reports are, relative to `review.dir`.

    Returns:
        The course notes directory's path relative to the repository (e.g. \
        `course-notes`), None if it isn't inside it.
    """
    git_dir = settings.paths.git_dir
    notes = Path(_normalized(settings.paths.course_notes_dir))
    if not notes.is_relative_to(git_dir) or notes == git_dir:
        return None
    return PurePosixPath(notes.relative_to(git_dir).as_posix())


def deck_report_path(settings: "GlobalSettings", deck: str) -> Path:
    """Where a deck's report is: `<review.dir>/<deck directory>.md`.

    Args:
        settings: The repository's settings.
        deck: The deck's directory, relative to the repository.

    Returns:
        Its absolute path.
    """
    return review_dir(settings) / f"{deck}.md"


def _misplaced(settings: "GlobalSettings", path: Path) -> str:
    directory = _rel(settings, review_dir(settings))
    notes = course_notes_reports_dir(settings)
    chapters = (
        "" if notes is None else f", a course notes report (under {directory}/{notes}/)"
    )
    return (
        f"{_rel(settings, path)} is neither a shared section's report (under "
        f"{directory}/{SECTIONS_DIR}/){chapters} nor a deck's report "
        f"({directory}/<deck directory>.md, e.g. {directory}/<company>/<deck>.md): "
        "move it there (`git mv`); a deck's report whose deck was renamed follows "
        "it, one whose deck was removed goes"
    )


def deck_own_files(
    settings: "GlobalSettings", deck: str, at: str | None = None
) -> list[str]:
    """The files a deck's report records: the deck's own, under its directory.

    Its git-tracked files and the untracked ones git doesn't ignore (with
    `at`, the files of that commit), but not the `en/` translations (a deck
    pass reads the French), nor the files of a deck nested in it.

    Args:
        settings: The repository's settings.
        deck: The deck's directory, relative to the repository.
        at: A commit, for its files rather than the working tree's.

    Returns:
        Their paths relative to the repository, sorted.

    Raises:
        ReviewError: If git fails.
    """
    git_dir = settings.paths.git_dir
    if at is None:
        args = ["ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    else:
        args = ["ls-tree", "-r", "-z", "--name-only", at]
    out = _git(git_dir, *args, "--", deck)
    if out is None:
        msg = f"`git {args[0]}` failed on {deck} in {git_dir}"
        raise ReviewError(msg)
    root = PurePosixPath(deck)
    listed = sorted({PurePosixPath(p) for p in out.split("\0") if p})
    nested = {p.parent for p in listed if p.name == "deck.yml"} - {root}
    return [
        path.as_posix()
        for path in listed
        if "en" not in path.relative_to(root).parts[:-1]
        and not any(parent in nested for parent in path.parents)
        and (at is not None or (git_dir / path).is_file())
    ]


def locate(settings: "GlobalSettings", path: Path) -> Path:
    """Where a path given on the command line is.

    Returns:
        `path` if absolute; else from the current directory if there's \
        something there, else from the repository's root (absolute).

    Raises:
        ReviewError: If it's outside the repository.
    """
    git_dir = settings.paths.git_dir
    if path.is_absolute():
        found = path
    else:
        here = settings.paths.current_dir / path
        found = (
            here if here.exists() or not (git_dir / path).exists() else git_dir / path
        )
    found = Path(_normalized(found))
    if not found.is_relative_to(git_dir):
        msg = f"{path} is outside the repository {git_dir}"
        raise ReviewError(msg)
    return found


def _normalized(path: Path) -> str:
    # Resolved as the parser resolves the files it finds, and as `git_dir` is.
    return str(path.resolve())


def _in_content_dir(settings: "GlobalSettings", path: Path) -> bool:
    # In the shared content directory or a deck's own (`content/` next to a
    # `deck.yml`).
    if path.is_relative_to(settings.paths.content_dir):
        return True
    return any(
        parent.is_relative_to(settings.paths.git_dir)
        and parent.name == "content"
        and (parent.parent / "deck.yml").is_file()
        for parent in (path, *path.parents)
    )


def _content_root(settings: "GlobalSettings", path: Path) -> Path | None:
    if path.is_relative_to(settings.paths.content_dir):
        return settings.paths.content_dir
    for parent in (path, *path.parents):
        if parent.name == "content" and (parent.parent / "deck.yml").is_file():
            return parent
    return None


def is_content_path(settings: "GlobalSettings", path: Path) -> bool:
    """Whether `path` (absolute) is a content file, shared or a deck's own.

    Returns:
        True if its name is a content file's and it is under a content directory.
    """
    from ..utils import is_content_file

    return is_content_file(path, settings.file_extensions) and _in_content_dir(
        settings, path
    )


########################################################################################
# git                                                                                  #
########################################################################################


def _git(git_dir: Path, *args: str, stdin: str | None = None) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(git_dir), *args],
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )
    return None if result.returncode else result.stdout


def blobs(git_dir: Path, paths: Iterable[str]) -> dict[str, str]:
    """The blob sha (`git hash-object`) of each existing file of `paths`.

    Args:
        git_dir: The repository's root.
        paths: Relative to it.

    Returns:
        Each existing file's sha, by path.

    Raises:
        ReviewError: If git fails.
    """
    existing = [path for path in dict.fromkeys(paths) if (git_dir / path).is_file()]
    if not existing:
        return {}
    out = _git(git_dir, "hash-object", "--stdin-paths", stdin="\n".join(existing))
    if out is None:
        msg = f"`git hash-object` failed in {git_dir}"
        raise ReviewError(msg)
    return dict(zip(existing, out.split(), strict=True))


def _contents(git_dir: Path, shas: Iterable[str]) -> dict[str, bytes | None]:
    # The content of each blob, None if it's not in the repository's objects.
    wanted = list(dict.fromkeys(shas))
    if not wanted:
        return {}
    result = subprocess.run(
        ["git", "-C", str(git_dir), "cat-file", "--batch"],
        input=("\n".join(wanted) + "\n").encode(),
        capture_output=True,
        check=False,
    )
    found: dict[str, bytes | None] = dict.fromkeys(wanted)
    out, position = result.stdout, 0
    for sha in wanted:
        end = out.find(b"\n", position)
        if end < 0:
            break
        header = out[position:end].split()
        position = end + 1
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            found[sha] = out[position : position + size]
            position += size + 1
        elif len(header) == 3:  # Another kind of object: skip its content.
            position += int(header[2]) + 1
    return found


def _head(git_dir: Path) -> str:
    head = _git(git_dir, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if not head:
        msg = f"{git_dir} has no commit yet: commit something before marking reviews"
        raise ReviewError(msg)
    return head.strip()


def fork_point(git_dir: Path) -> tuple[str | None, str]:
    """Where this checkout's branch left the line everyone's work meets on.

    That line is the branch of the repository's main checkout (as `deckz
    worktree land` lands onto): the fork point is HEAD's merge base with
    it. On that branch itself, it's the merge base with its upstream, and
    HEAD when there's none (every commit is then shared).

    Returns:
        The fork point's sha (None without a commit), and the branch or \
        upstream it's computed against.
    """
    from ..exceptions import WorktreeError
    from ..worktrees import main_checkout

    head = _git(git_dir, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if not head:
        return None, "HEAD"
    try:
        main = main_checkout(git_dir)
    except WorktreeError:
        main = git_dir
    main_branch = (
        _git(main, "symbolic-ref", "--quiet", "--short", "HEAD") or ""
    ).strip()
    branch = (_git(git_dir, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip()
    if main_branch and branch != main_branch:
        base = _git(git_dir, "merge-base", "HEAD", f"refs/heads/{main_branch}")
        if base:
            return base.strip(), main_branch
    tracked = _git(
        git_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    if tracked and (base := _git(git_dir, "merge-base", "HEAD", "@{upstream}")):
        return base.strip(), tracked.strip()
    return head.strip(), "HEAD"


def _blob_at(git_dir: Path, commit: str, path: str) -> str | None:
    out = _git(git_dir, "rev-parse", "--verify", "--quiet", f"{commit}:{path}")
    return out.strip() if out else None


def _branch_versions(git_dir: Path, fork: str, path: str) -> set[str]:
    # The versions of `path` this branch's own commits made since `fork`
    # (those descending from it: not the ones a merge brought in), and the
    # staged one.
    versions = set()
    out = _git(
        git_dir,
        "log",
        "--ancestry-path",
        "--no-renames",
        "--raw",
        "--no-abbrev",
        "--format=",
        f"{fork}..HEAD",
        "--",
        path,
    )
    for line in (out or "").splitlines():
        fields = line.split()
        if line.startswith(":") and len(fields) >= 4:
            versions.add(fields[3])
    staged = _git(git_dir, "ls-files", "--stage", "--", path)
    if staged and len(fields := staged.split()) >= 2:
        versions.add(fields[1])
    return versions


def changed_elsewhere(
    git_dir: Path, fork: str | None, path: str, recorded: str
) -> bool:
    """Whether `path`'s changes since its review include work from elsewhere.

    They do when the version at the fork point (`fork_point`) is neither
    the one reviewed nor one this branch's own commits made after it:
    commits on the main line reached the file since the review, and they
    are in the working tree's version (it descends from the fork point).
    A file the fork point lacks is this branch's own.

    Returns:
        True if so.
    """
    if fork is None:
        return False
    at_fork = _blob_at(git_dir, fork, path)
    if at_fork is None or at_fork == recorded:
        return False
    return recorded not in _branch_versions(git_dir, fork, path)


########################################################################################
# Reports                                                                              #
########################################################################################


@dataclass(frozen=True)
class _FrontMatter:
    text: str
    """The whole file."""
    start: int
    """Where the YAML starts (after the opening `---` line), -1 if none."""
    end: int
    """Where the YAML ends (the closing line's start)."""


def _front_matter(text: str) -> _FrontMatter:
    if not text.startswith(_FENCE) or text[3:4] not in ("\n", "\r"):
        return _FrontMatter(text, -1, -1)
    start = text.index("\n") + 1
    position = start
    while position < len(text):
        end = text.find("\n", position)
        line = text[position : len(text) if end < 0 else end].rstrip("\r")
        if line in (_FENCE, "..."):
            return _FrontMatter(text, start, position)
        if end < 0:
            break
        position = end + 1
    msg = "its front matter has no closing `---` line"
    raise ReviewError(msg)


@dataclass(frozen=True)
class _Reviewed:
    # A well-formed `reviewed` value, and what's wrong with it.
    date: date | None
    base: str | None
    files: dict[str, str]
    own: dict[str, tuple[date, str]]
    problems: list[str]


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _validated(data: Any) -> _Reviewed:
    problems: list[str] = []
    if not isinstance(data, dict):
        return _Reviewed(None, None, {}, {}, ["`reviewed` is not a mapping"])
    if unknown := sorted(set(data) - {"date", "base", "files"}):
        problems.append(f"`reviewed` has unknown keys: {', '.join(map(str, unknown))}")
    when = _date(data.get("date"))
    if when is None:
        problems.append(f"`reviewed.date` is not a date: {data.get('date')!r}")
    base = _sha(data.get("base"))
    if base is None:
        problems.append(f"`reviewed.base` is not a commit sha: {data.get('base')!r}")
    found, own = _validated_files(data.get("files"), problems)
    return _Reviewed(when, base, found, own, problems)


def _sha(value: Any) -> str | None:
    # A 40-hex sha. One of digits only would read as an integer: `mark`
    # quotes it (`yaml.safe_dump` does).
    return value if isinstance(value, str) and _SHA.fullmatch(value) else None


def _validated_files(
    files: Any, problems: list[str]
) -> tuple[dict[str, str], dict[str, tuple[date, str]]]:
    # The `reviewed.files` value's well-formed entries (blobs, and the own
    # date and base of those that have one); the others' problems go to
    # `problems`.
    found: dict[str, str] = {}
    own: dict[str, tuple[date, str]] = {}
    if files is None:
        return found, own
    if not isinstance(files, dict):
        problems.append("`reviewed.files` is not a mapping")
        return found, own
    for path, value in files.items():
        pure = PurePosixPath(str(path))
        if pure.is_absolute() or ".." in pure.parts or not str(path):
            problems.append(
                f"`reviewed.files` has a path not in the repository: {path}"
            )
        elif isinstance(value, dict):
            entry = _validated_entry(str(path), value, problems)
            if entry is not None:
                found[str(path)], own[str(path)] = entry
        elif (blob := _sha(value)) is None:
            problems.append(f"`reviewed.files`' {path} is not a blob sha: {value!r}")
        else:
            found[str(path)] = blob
    return found, own


def _validated_entry(
    path: str, value: dict[Any, Any], problems: list[str]
) -> tuple[str, tuple[date, str]] | None:
    # A file's entry with its own date: `{blob, date, base}`.
    wrong = []
    if unknown := sorted(set(value) - {"blob", "date", "base"}):
        wrong.append(f"unknown keys {', '.join(map(str, unknown))}")
    blob, when, base = (
        _sha(value.get("blob")),
        _date(value.get("date")),
        _sha(value.get("base")),
    )
    if blob is None:
        wrong.append(f"`blob` is not a blob sha: {value.get('blob')!r}")
    if when is None:
        wrong.append(f"`date` is not a date: {value.get('date')!r}")
    if base is None:
        wrong.append(f"`base` is not a commit sha: {value.get('base')!r}")
    if wrong or blob is None or when is None or base is None:
        problems.append(f"`reviewed.files`' {path}: {'; '.join(wrong)}")
        return None
    return blob, (when, base)


def _reviewed_value(text: str) -> Any:
    # The front matter's `reviewed` value, None if there's none.
    import yaml

    front = _front_matter(text)
    if front.start < 0:
        return None
    try:
        data = yaml.safe_load(text[front.start : front.end])
    except yaml.YAMLError as error:
        msg = f"its front matter is not valid YAML: {error}"
        raise ReviewError(msg) from error
    if data is None:
        return None
    if not isinstance(data, dict):
        msg = "its front matter is not a YAML mapping"
        raise ReviewError(msg)
    return data.get(_KEY)


def read_report(settings: "GlobalSettings", path: Path) -> Report:
    """Read a report's `reviewed` front matter.

    Returns:
        It, with no date, base or files if it has no `reviewed` key.

    Raises:
        ReviewError: If its front matter or `reviewed` is malformed.
    """
    rel = _rel(settings, path)
    try:
        value = _reviewed_value(path.read_text(encoding="utf8"))
        if value is None:
            return Report(rel, None, None, {})
        found = _validated(value)
        problems = found.problems
    except ReviewError as error:
        problems = [str(error)]
    else:
        if not problems:
            return Report(
                rel,
                found.date,
                found.base,
                dict(sorted(found.files.items())),
                found.own,
            )
    msg = (
        f"{rel}: {'; '.join(problems)}: fix the front matter by hand "
        "(`deckz check review-headers`)"
    )
    raise ReviewError(msg)


def report_paths(settings: "GlobalSettings") -> list[Path]:
    """Every report: the Markdown files under `review.dir`.

    Returns:
        Their absolute paths, sorted.
    """
    directory = review_dir(settings)
    if not directory.is_dir():
        return []
    return sorted(directory.rglob("*.md"))


def all_reports(settings: "GlobalSettings") -> tuple[list[Report], list[str]]:
    """Read every report.

    Returns:
        The reports read, and the problems of those that couldn't be.
    """
    found, problems = [], []
    for path in report_paths(settings):
        try:
            found.append(read_report(settings, path))
        except ReviewError as error:
            problems.append(str(error))
    return found, problems


def reports_among(
    settings: "GlobalSettings", paths: Iterable[Path] | None
) -> list[Path]:
    """The reports among `paths`, as a check given paths reads them.

    Args:
        settings: The repository's settings.
        paths: Absolute paths; None for every report.

    Returns:
        The existing reports among them, sorted.
    """
    if paths is None:
        return report_paths(settings)
    directory = review_dir(settings)
    return sorted(
        path
        for path in paths
        if path.suffix == ".md" and path.is_relative_to(directory) and path.is_file()
    )


def header_problems(
    settings: "GlobalSettings", paths: Iterable[Path] | None
) -> list[str]:
    """The `review-headers` check: every report's `reviewed` is well formed.

    Its front matter parses, `reviewed` has a date, a base commit and 40-hex
    blob shas, and every recorded path exists. And the report is where its
    kind puts it (`report_kind`).

    Args:
        settings: The repository's settings.
        paths: Only check the reports among these (absolute paths); None for \
            every report.

    Returns:
        The problems, one line each; none when `review.dir` is unset.
    """
    if settings.review.dir is None:
        return []
    git_dir = settings.paths.git_dir
    problems = []
    for path in reports_among(settings, paths):
        if report_kind(settings, path) is None:
            problems.append(_misplaced(settings, path))
        try:
            report = read_report(settings, path)
        except ReviewError as error:
            problems.append(str(error))
            continue
        problems.extend(
            f"{report.path}: records {recorded}, which doesn't exist: if it was "
            f"renamed, `deckz review mark {report.path} --forget {recorded} "
            "<new path>`, else `--forget` it alone"
            for recorded in report.files
            if not (git_dir / recorded).exists()
        )
    return problems


@cache
def _no_alias_dumper() -> type:
    import yaml

    class NoAliasDumper(yaml.SafeDumper):
        # Several files sharing a date object would get `&id001`/`*id001`.
        def ignore_aliases(self, data: Any) -> bool:
            return True

    return NoAliasDumper


def _write_report(
    path: Path,
    report_date: date,
    base: str,
    files: Mapping[str, str],
    own: Mapping[str, tuple[date, str]] | None = None,
) -> None:
    # Rewrite only the `reviewed` key of `path`'s front matter (creating the
    # file or the front matter), everything else byte for byte. A file of
    # `own` marked on another day or commit than the report's gets its own
    # entry (a rule's time compares the base's).
    import yaml

    from ..utils import write_atomic

    own = own or {}
    entries: dict[str, Any] = {}
    for file, blob in sorted(files.items()):
        when, commit = own.get(file, (report_date, base))
        entries[file] = (
            blob
            if (when, commit) == (report_date, base)
            else {"blob": blob, "date": when, "base": commit}
        )
    block = yaml.dump(
        {
            _KEY: {
                "date": report_date,
                "base": base,
                "files": entries,
            }
        },
        Dumper=_no_alias_dumper(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )
    text = path.read_text(encoding="utf8") if path.is_file() else ""
    front = _front_matter(text)
    if front.start < 0:
        new = f"{_FENCE}\n{block}{_FENCE}\n{text}"
    else:
        yaml_text = text[front.start : front.end]
        span = _key_span(yaml_text)
        if span is None:
            new = text[: front.end] + block + text[front.end :]
        else:
            begin, finish = span
            new = text[: front.start + begin] + block + text[front.start + finish :]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, new.encode("utf8"))


def _key_span(yaml_text: str) -> tuple[int, int] | None:
    # Where the top-level `reviewed:` entry is in `yaml_text`: from its line to
    # the next top-level line, trailing blank lines left out.
    lines = yaml_text.splitlines(keepends=True)
    offset, begin = 0, None
    finish = 0
    for line in lines:
        if begin is None:
            if re.match(rf"{_KEY}\s*:", line):
                begin = offset
                finish = offset + len(line)
        elif line.strip() == "":
            pass
        elif line[0] in " \t":
            finish = offset + len(line)
        else:
            break
        offset += len(line)
    return None if begin is None else (begin, finish)


########################################################################################
# Status                                                                               #
########################################################################################


@cache
def _commit_time(git_dir: Path, sha: str) -> int:
    out = _git(git_dir, "show", "-s", "--format=%ct", f"{sha}^{{commit}}")
    return int(out.strip()) if out and out.strip().isdigit() else 0


def marks_index(
    git_dir: Path, reports: Iterable[Report]
) -> dict[str, tuple[Mark, ...]]:
    """Every recorded path's marks, the most recent first.

    Returns:
        The marks of each path, by path.
    """
    index: dict[str, list[Mark]] = {}
    for report in reports:
        if report.date is None or report.base is None:
            continue
        for path, blob in report.files.items():
            when, base = report.own.get(path, (report.date, report.base))
            index.setdefault(path, []).append(Mark(report.path, when, base, blob))
    return {
        path: tuple(
            sorted(
                marks,
                key=lambda mark: (
                    mark.date,
                    _commit_time(git_dir, mark.base) if len(marks) > 1 else 0,
                ),
                reverse=True,
            )
        )
        for path, marks in index.items()
    }


def _line_counts(old: bytes, new: bytes) -> tuple[int, int]:
    matcher = SequenceMatcher(
        None,
        old.decode("utf8", "replace").splitlines(),
        new.decode("utf8", "replace").splitlines(),
    )
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            removed += i2 - i1
            added += j2 - j1
    return added, removed


def _touched(starts: list[int], lines: list[str], begin: int, end: int) -> set[int]:
    # The frames (0: the lines before the first heading) of lines[begin:end]
    # that aren't blank; an empty range falls in the frame of the line before.
    if begin == end:
        return {bisect_right(starts, begin - 1)}
    return {bisect_right(starts, i) for i in range(begin, end) if lines[i].strip()}


def _changed_frames(old: bytes, new: bytes) -> int:
    # The frames a line added or removed falls in, counted in each version.
    from ..components.frame_markers import frame_headings

    old_text = old.decode("utf8", "replace")
    new_text = new.decode("utf8", "replace")
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    old_starts = [line for line, _ in frame_headings(old_text)]
    new_starts = [line for line, _ in frame_headings(new_text)]
    in_old: set[int] = set()
    in_new: set[int] = set()
    matcher = SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            in_old |= _touched(old_starts, old_lines, i1, i2)
            in_new |= _touched(new_starts, new_lines, j1, j2)
    return max(len(in_old), len(in_new))


def _frames_to_review(review: FileReview) -> int:
    # A file due under a rule is read whole again, against the rule.
    if review.state == "unreviewed" or review.due:
        return review.frames or 0
    if review.state == "stale":
        if review.changed_frames is not None:
            return review.changed_frames
        return review.frames or 0
    return 0


def review_files(
    settings: "GlobalSettings",
    paths: Sequence[str],
    index: Mapping[str, tuple[Mark, ...]],
) -> list[FileReview]:
    """Each of `paths`' state against the marks of `index`.

    Args:
        settings: The repository's settings.
        paths: Relative to the repository.
        index: The marks, from `marks_index`.

    Returns:
        One per path, in their order.
    """
    from .sections_analyzer import frame_count

    git_dir = settings.paths.git_dir
    current = blobs(git_dir, [path for path in paths if path in index])
    stale = {
        path: index[path][0].blob
        for path in paths
        if path in index and path in current and current[path] != index[path][0].blob
    }
    old = _contents(git_dir, stale.values())
    found = []
    for path in paths:
        absolute = git_dir / path
        frames = (
            frame_count(absolute)
            if absolute.is_file() and is_content_path(settings, absolute)
            else None
        )
        marks = index.get(path, ())
        due = due_rules(settings, path, marks[0]) if marks else ()
        if not marks:
            found.append(FileReview(path, "unreviewed", frames=frames))
        elif path not in current:
            found.append(FileReview(path, "deleted", marks))
        elif path not in stale:
            state: State = "due" if due else "fresh"
            found.append(FileReview(path, state, marks, frames=frames, due=due))
        elif (reviewed := old.get(stale[path])) is None:
            found.append(FileReview(path, "stale", marks, frames=frames, due=due))
        else:
            text = absolute.read_bytes()
            added, removed = _line_counts(reviewed, text)
            changed = None if frames is None else _changed_frames(reviewed, text)
            found.append(
                FileReview(path, "stale", marks, added, removed, frames, changed, due)
            )
    return found


def due_rules(
    settings: "GlobalSettings", path: str, mark: Mark
) -> tuple["ReviewRule", ...]:
    """The rules (`review.rules`) covering a file that took effect after its mark.

    A rule whose `since` is a day took effect after a mark of an earlier day;
    one whose `since` is a time, after a mark whose base commit is older (by
    its commit time; by its mark's day if this clone lacks it).

    Args:
        settings: The repository's settings.
        path: Relative to the repository.
        mark: The file's mark (the one used).

    Returns:
        Those rules, in `review.rules`' order.
    """
    pure = PurePosixPath(path)
    return tuple(
        rule
        for rule in settings.review.rules
        if pure.full_match(rule.paths)
        and _before(settings.paths.git_dir, mark, rule.since)
    )


def _before(git_dir: Path, mark: Mark, since: date) -> bool:
    if not isinstance(since, datetime):
        return mark.date < since
    if committed := _commit_time(git_dir, mark.base):
        return committed < since.timestamp()
    return mark.date < since.date()


def _files_of(deck: "Deck") -> list[Path]:
    # Its files, in order, each once (resolved, as the parser resolves them).
    from .sections_analyzer import ordered_files

    return list(
        dict.fromkeys(
            Path(path)
            for part in deck.parts.values()
            for path in ordered_files(part.nodes)
        )
    )


def deck_files(settings: "DeckSettings") -> list[Path]:
    """A deck's content files, in French, as `deckz show paths` resolves them.

    Returns:
        Their absolute paths, in the deck's order, each once.
    """
    return _files_of(_parsed(settings))


def _parsed(settings: "DeckSettings") -> "Deck":
    from ..components.factory import DeckSettingsFactory

    return (
        DeckSettingsFactory(settings, lang="fr")
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )


def _deck_chapters(settings: "DeckSettings", deck: "Deck") -> list[str]:
    # Its course notes' written French chapters, in its order, each once.
    from ..course_notes import ChapterStatus, entries

    return list(
        dict.fromkeys(
            _rel(settings, Path(_normalized(entry.chapter)))
            for entry in entries(settings, deck, "fr")
            if entry.status in (ChapterStatus.WRITTEN, ChapterStatus.COVERED)
        )
    )


def deck_covered_paths(settings: "DeckSettings") -> set[str]:
    """The files through which a report covers a deck.

    Its content files, and its course notes' written French chapters: a
    report recording one of them is about the deck (`review findings
    <deck>`, `deckz dashboard`).

    Returns:
        Their paths, relative to the repository.
    """
    parsed = _parsed(settings)
    return {
        *(_rel(settings, path) for path in _files_of(parsed)),
        *_deck_chapters(settings, parsed),
    }


def _chapters_under(settings: "GlobalSettings", target: Path) -> list[str]:
    # The French chapters of the course notes under `target`.
    from ..course_notes import chapter_path, chapters

    found = (
        Path(_normalized(chapter_path(settings, path, "fr")))
        for path, lang in chapters(settings)
        if lang == "fr"
    )
    return sorted(_rel(settings, p) for p in found if p.is_relative_to(target))


def used_files(
    settings: "GlobalSettings", decks: Mapping[Path, "ParsedDeck"] | None = None
) -> dict[str, set[str]]:
    """Every content file some deck includes, in French, with those decks.

    Args:
        settings: The repository's settings.
        decks: Every deck parsed in French (`utils.all_decks`), when already \
            parsed: that takes seconds.

    Returns:
        The decks' directories relative to the repository, by file relative \
        to it.
    """
    from ..utils import all_decks

    git_dir = settings.paths.git_dir
    if decks is None:
        decks = all_decks(git_dir, "fr")
    used: dict[str, set[str]] = {}
    for deck_path, parsed in decks.items():
        for path in _files_of(parsed.deck):
            used.setdefault(_rel(settings, path), set()).add(deck_path.as_posix())
    return used


def expand(
    settings: "GlobalSettings",
    targets: Iterable[Path],
    used: Mapping[str, set[str]] | None = None,
) -> list[str]:
    """The files the paths given to `status`, `mark` or `diff` stand for.

    A file stands for itself; a content directory for the content files some
    deck includes under it (its `en/` translations left out); a deck's
    directory for the content files it resolves to; a course notes
    directory for its French chapters; any other directory for its
    git-tracked files. A path that doesn't exist stands for itself (a file
    deleted or renamed, for `--forget`).

    Args:
        settings: The repository's settings.
        targets: Absolute paths, from `locate`.
        used: The content files some deck includes, when already known.

    Returns:
        Paths relative to the repository, without duplicates.
    """
    from ..configuring.settings import DeckSettings

    git_dir = settings.paths.git_dir
    found: dict[str, None] = {}
    for target in targets:
        if target.is_file() or not target.exists():
            found[_rel(settings, target)] = None
        elif (target / "deck.yml").is_file():
            deck = DeckSettings.from_yaml(target, git_dir=git_dir)
            for path in deck_files(deck):
                found[_rel(settings, path)] = None
        elif _in_content_dir(settings, target):
            if used is None:
                used = used_files(settings)
            found.update(dict.fromkeys(used_under(settings, target, used)))
        elif target.is_relative_to(Path(_normalized(settings.paths.course_notes_dir))):
            found.update(dict.fromkeys(_chapters_under(settings, target)))
        else:
            listed = _git(git_dir, "ls-files", "-z", "--", _rel(settings, target)) or ""
            for path in sorted(p for p in listed.split("\0") if p):
                found[path] = None
    return list(found)


def used_under(
    settings: "GlobalSettings", target: Path, used: Mapping[str, set[str]]
) -> list[str]:
    """The content files of `used` under the content directory `target`.

    Returns:
        Their paths relative to the repository, sorted, their `en/` \
        translations left out.
    """
    git_dir = settings.paths.git_dir
    root = _content_root(settings, target) or target
    return [
        path
        for path in sorted(used)
        if (git_dir / path).is_relative_to(target)
        and "en" not in (git_dir / path).relative_to(root).parts[:-1]
    ]


def _owning_section(settings: "GlobalSettings", path: Path, sections: set[str]) -> str:
    # The innermost shared section whose directory holds `path` (its own
    # directory when none does, `.` for the content directory itself); a
    # deck's own content file: its directory, from the repository's root.
    content_dir = settings.paths.content_dir
    if not path.is_relative_to(content_dir):
        return _rel(settings, path.parent)
    relative = path.parent.relative_to(content_dir)
    return next(
        (
            candidate.as_posix()
            for candidate in (relative, *relative.parents)
            if candidate.as_posix() in sections
        ),
        relative.as_posix(),
    )


def deck_review(
    settings: "DeckSettings",
    reports: Sequence[Report],
    index: Mapping[str, tuple[Mark, ...]] | None = None,
) -> DeckReview:
    """A deck's content files' states, by section, the reports' other files.

    And its pass (`DeckPass`), and its written French course notes chapters.

    Returns:
        Its review.
    """
    from ..utils import shared_section_ids

    git_dir = settings.paths.git_dir
    if index is None:
        index = marks_index(git_dir, reports)
    sections = set(shared_section_ids(settings.paths.content_dir))
    parsed = _parsed(settings)
    grouped: dict[str, list[str]] = {}
    for path in _files_of(parsed):
        grouped.setdefault(_owning_section(settings, path, sections), []).append(
            _rel(settings, path)
        )
    chapters = _deck_chapters(settings, parsed)
    deck = _rel(settings, settings.paths.current_dir)
    deck_pass = _deck_pass(settings, deck, reports)
    passed = {review.path for review in deck_pass.files}
    content = {path for files in grouped.values() for path in files}
    covering = {mark.report for path in content for mark in index.get(path, ())}
    others = sorted(
        {
            path
            for report in reports
            if report.path in covering
            for path in report.files
            if path not in content
            and path not in passed
            and path not in chapters
            and not is_content_path(settings, git_dir / path)
        }
    )
    every = review_files(
        settings,
        [*(p for files in grouped.values() for p in files), *others, *chapters],
        index,
    )
    by_path = {review.path: review for review in every}
    return DeckReview(
        deck,
        tuple(
            SectionReview(section, tuple(by_path[path] for path in files))
            for section, files in grouped.items()
        ),
        tuple(by_path[path] for path in others),
        deck_pass,
        tuple(by_path[path] for path in chapters),
    )


def _deck_pass(
    settings: "GlobalSettings", deck: str, reports: Sequence[Report]
) -> DeckPass:
    # The deck's own files against its report's marks alone: a file a
    # section report also records, marked later there, doesn't make the
    # deck's pass hold.
    rel = _rel(settings, deck_report_path(settings, deck))
    report = next((r for r in reports if r.path == rel), None)
    recorded = report.files if report is not None else {}
    paths = list(dict.fromkeys([*deck_own_files(settings, deck), *recorded]))
    own_index = marks_index(settings.paths.git_dir, [report] if report else [])
    return DeckPass(
        rel,
        report.date if report else None,
        report.base if report else None,
        tuple(review_files(settings, paths, own_index)),
    )


def ranking(
    settings: "GlobalSettings",
    reports: Sequence[Report],
    index: Mapping[str, tuple[Mark, ...]] | None = None,
) -> list[RankedSection]:
    """Every shared section some deck uses, the most worth reviewing first.

    A file belongs to the innermost shared section whose directory holds it
    (its own directory, when no section's does). A section's score is the
    number of decks including at least one of its files times its frames to
    review: all those of its unreviewed files, and those the changes of its
    stale files touch.

    Returns:
        The sections, by score, then decks, then path.
    """
    from ..utils import shared_section_ids

    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    if index is None:
        index = marks_index(git_dir, reports)
    sections = set(shared_section_ids(content_dir))
    used = used_files(settings)
    grouped: dict[str, list[str]] = {}
    decks: dict[str, set[str]] = {}
    for path in sorted(used):
        absolute = git_dir / path
        if not absolute.is_relative_to(content_dir):
            continue
        section = _owning_section(settings, absolute, sections)
        grouped.setdefault(section, []).append(path)
        decks.setdefault(section, set()).update(used[path])
    every = review_files(
        settings, [path for files in grouped.values() for path in files], index
    )
    by_path = {review.path: review for review in every}
    ranked = []
    for section, files in grouped.items():
        reviews = tuple(by_path[path] for path in files)
        to_review = sum(_frames_to_review(review) for review in reviews)
        ranked.append(
            RankedSection(
                section, len(decks[section]), reviews, len(decks[section]) * to_review
            )
        )
    ranked.sort(key=lambda r: (-r.score, -r.decks, r.section))
    return ranked


@dataclass(frozen=True)
class TargetReview:
    target: str
    """As given, relative to the repository."""
    deck: DeckReview | None
    """A deck's review, if the target is a deck's directory."""
    files: tuple[FileReview, ...] = ()
    """Else, the files it stands for (`expand`)."""


@dataclass(frozen=True)
class ReviewStatus:
    ranked: tuple[RankedSection, ...]
    """With no target, every shared section some deck uses (`ranking`)."""
    targets: tuple[TargetReview, ...]
    problems: tuple[str, ...]
    """The reports that couldn't be read, each with why."""


def review_status(settings: "GlobalSettings", targets: Sequence[Path]) -> ReviewStatus:
    """`deckz review status`: the targets' files, or the ranking of the sections.

    Args:
        settings: The repository's settings.
        targets: Decks' directories or paths, absolute (`locate`); none for \
            the ranking.

    Returns:
        The status. Fails (`review_dir`) if `review.dir` is unset.
    """
    from ..configuring.settings import DeckSettings

    review_dir(settings)
    reports, problems = all_reports(settings)
    index = marks_index(settings.paths.git_dir, reports)
    if not targets:
        return ReviewStatus(
            tuple(ranking(settings, reports, index)), (), tuple(problems)
        )
    # Parsing every deck takes seconds: once for all the content directories.
    used = (
        used_files(settings)
        if any(
            target.is_dir()
            and not (target / "deck.yml").is_file()
            and _in_content_dir(settings, target)
            for target in targets
        )
        else None
    )
    found = []
    for target in targets:
        shown = _rel(settings, target) or "."
        if (target / "deck.yml").is_file():
            deck = DeckSettings.from_yaml(target, git_dir=settings.paths.git_dir)
            found.append(TargetReview(shown, deck_review(deck, reports, index)))
        else:
            reviews = review_files(settings, expand(settings, [target], used), index)
            found.append(TargetReview(shown, None, tuple(reviews)))
    return ReviewStatus((), tuple(found), tuple(problems))


def deck_counts(
    settings: "DeckSettings", index: Mapping[str, tuple[Mark, ...]]
) -> tuple[int, int, int] | None:
    """How many of a deck's content files are unreviewed, stale, and in all.

    Cheap enough for `deckz status`: the deck is parsed once, and only the
    files a report records are hashed.

    Args:
        settings: The deck's settings.
        index: The marks, from `marks_index`.

    Returns:
        `(unreviewed, stale, total)`, or None if the deck doesn't parse.
    """
    from ..exceptions import DeckzError

    try:
        files = deck_files(settings)
    except DeckzError:
        return None
    git_dir = settings.paths.git_dir
    paths = [_rel(settings, path) for path in files]
    current = blobs(git_dir, [path for path in paths if path in index])
    unreviewed = sum(path not in index for path in paths)
    stale = sum(
        path in index and current.get(path) != index[path][0].blob for path in paths
    )
    return unreviewed, stale, len(paths)


########################################################################################
# Diff and mark                                                                        #
########################################################################################


def _report_path(settings: "GlobalSettings", report: Path) -> Path:
    directory = review_dir(settings)
    if report.suffix != ".md" or not report.is_relative_to(directory):
        msg = (
            f"{report} is not a report: a report is a Markdown file under "
            f"{_rel(settings, directory)} (`review.dir`)"
        )
        raise ReviewError(msg)
    return report


def diff(
    settings: "GlobalSettings", report: Path, paths: Sequence[Path] = ()
) -> list[FileDiff]:
    """What changed in a report's files since their review.

    Args:
        settings: The repository's settings.
        report: The report (absolute, from `locate`).
        paths: Only these of its files (absolute, expanded as `expand` \
            does); every recorded file if empty.

    Returns:
        One per recorded file whose working-tree version differs from the \
        one reviewed (or that is gone), in the report's order.

    Raises:
        ReviewError: If the report doesn't exist or can't be read.
    """
    report = _report_path(settings, report)
    if not report.is_file():
        msg = f"no report {_rel(settings, report)}: `deckz review mark` creates one"
        raise ReviewError(msg)
    recorded = read_report(settings, report).files
    wanted = set(expand(settings, paths)) if paths else set(recorded)
    git_dir = settings.paths.git_dir
    chosen = {path: blob for path, blob in recorded.items() if path in wanted}
    current = blobs(git_dir, chosen)
    changed = {path: blob for path, blob in chosen.items() if current.get(path) != blob}
    old = _contents(git_dir, changed.values())
    found = []
    for path, blob in changed.items():
        if path not in current:
            found.append(FileDiff(path, "deleted", blob, None, None, None))
            continue
        reviewed = old.get(blob)
        if reviewed is None:
            found.append(FileDiff(path, "stale", blob, None, None, None))
            continue
        new = (git_dir / path).read_bytes()
        added, removed = _line_counts(reviewed, new)
        text = "".join(
            line if line.endswith("\n") else line + "\n"
            for line in unified_diff(
                reviewed.decode("utf8", "replace").splitlines(keepends=True),
                new.decode("utf8", "replace").splitlines(keepends=True),
                fromfile=f"a/{path} (reviewed {blob[:10]})",
                tofile=f"b/{path}",
            )
        )
        found.append(FileDiff(path, "stale", blob, added, removed, text))
    return found


def mark(
    settings: "GlobalSettings",
    report: Path,
    paths: Sequence[Path] = (),
    *,
    accept: Sequence[Path] = (),
    forget: Sequence[Path] = (),
    at: str | None = None,
    today: date | None = None,
) -> MarkResult:
    """Record the working-tree version of files as reviewed in a report.

    Creates the report (front matter only) if it doesn't exist. With no
    `paths`, refreshes every file it records, and in a deck's report also
    records the deck's own files (`deck_own_files`), which its deck's
    directory stands for there too; a deck's report refuses shared content,
    which section reports review. A recorded file whose change since its
    review came from elsewhere (`changed_elsewhere`) is refused, unless in
    `accept`; the others are marked all the same. The report's `date` and
    `base` (HEAD) are set whenever a file is marked or forgotten; the files
    recorded but not marked this time keep their own (the report's former
    ones, if they had none).

    With `at`, records the versions of a past commit instead, to register a
    review made then, of files the report doesn't record yet (so
    `changed_elsewhere` has nothing to refuse), with that commit's date and
    the commit as their base: the report's own if it records nothing yet.
    A file renamed since is found under its path at that commit (git's
    rename detection, from the commit to HEAD). Files changed since show
    stale.

    Args:
        settings: The repository's settings.
        report: The report (absolute, from `locate`).
        paths: Files to add or refresh (absolute, expanded as `expand` does).
        accept: Files to mark even though their change came from elsewhere \
            (once read with `deckz review diff`).
        forget: Files to remove from the report (deleted or renamed).
        at: A commit of this branch's history whose versions to record.
        today: The date to record, today by default (ignored with `at`).

    Returns:
        What was done.

    Raises:
        ReviewError: If `report` isn't a report (under `review.dir`, where \
            its kind puts it) or can't be read, there's nothing to mark, or \
            `at` doesn't apply (not a commit of this branch, a file the \
            report already records, a file missing at that commit).
    """
    report = _report_path(settings, report)
    kind = report_kind(settings, report)
    if kind is None:
        raise ReviewError(_misplaced(settings, report))
    deck = kind[1]
    created = not report.is_file()
    existing = (
        read_report(settings, report)
        if not created
        else Report(_rel(settings, report), None, None, {})
    )
    if at is not None:
        if accept or forget:
            msg = "--at registers a past review: it takes no --accept or --forget"
            raise ReviewError(msg)
        return _mark_at(settings, report, at, paths, existing, deck, created=created)
    return _mark_now(
        settings,
        report,
        paths,
        existing,
        deck,
        accept=accept,
        forget=forget,
        created=created,
        today=today,
    )


def _mark_now(
    settings: "GlobalSettings",
    report: Path,
    paths: Sequence[Path],
    existing: Report,
    deck: str | None,
    *,
    accept: Sequence[Path],
    forget: Sequence[Path],
    created: bool,
    today: date | None,
) -> MarkResult:
    # `mark` without `at`: the working tree's versions. The files it doesn't
    # mark keep the day they were marked.
    git_dir = settings.paths.git_dir
    rel_report = _rel(settings, report)
    recorded = dict(existing.files)
    named = [_rel(settings, path) for path in forget]
    forgotten = [path for path in named if recorded.pop(path, None) is not None]
    not_recorded = [path for path in named if path not in forgotten]
    accepted = set(expand(settings, accept)) if accept else set()
    targets = _mark_targets(settings, paths, recorded, deck, accepted, forget)
    if not targets and not forgotten:
        msg = (
            f"nothing to mark in {rel_report}: name the files reviewed "
            f"(`deckz review mark {rel_report} <path>...`)"
        )
        raise ReviewError(msg)
    current = blobs(git_dir, targets)
    fork, against = fork_point(git_dir)
    added, refreshed, unchanged = [], [], []
    refused = _shared_content(settings, targets, deck, rel_report)
    shared = {path for path, _ in refused}
    for path in targets:
        if path in shared:
            continue
        blob = current.get(path)
        old = recorded.get(path)
        if blob is None:
            refused.append(
                (
                    path,
                    f"{path}: no such file: if it was deleted or renamed, "
                    f"`deckz review mark {rel_report} --forget {path}`",
                )
            )
        elif old is None:
            recorded[path] = blob
            added.append(path)
        elif old == blob:
            unchanged.append(path)
        elif path not in accepted and changed_elsewhere(git_dir, fork, path, old):
            refused.append(
                (
                    path,
                    f"{path}: changed since its review by commits from {against}, "
                    "which nobody reviewed: read them with `deckz review diff "
                    f"{rel_report} {path}`, then `deckz review mark {rel_report} "
                    f"--accept {path}`",
                )
            )
        else:
            recorded[path] = blob
            refreshed.append(path)
    if added or refreshed or unchanged or forgotten:
        own = _kept_marks(existing, recorded, {*added, *refreshed, *unchanged})
        _write_report(report, today or date.today(), _head(git_dir), recorded, own)
    return MarkResult(
        rel_report,
        created and report.is_file(),
        tuple(added),
        tuple(refreshed),
        tuple(unchanged),
        tuple(forgotten),
        tuple(refused),
        tuple(not_recorded),
    )


def _kept_marks(
    existing: Report, recorded: Mapping[str, str], marked: set[str]
) -> dict[str, tuple[date, str]]:
    # The date and base of each file still recorded and not marked again:
    # its own, else the report's former ones.
    if existing.date is None or existing.base is None:
        return {}
    former = (existing.date, existing.base)
    return {
        path: existing.own.get(path, former)
        for path in recorded
        if path in existing.files and path not in marked
    }


def _blobs_at(
    git_dir: Path, commit: str, paths: Sequence[str], at: str
) -> dict[str, str]:
    # Each path's blob at `commit`, under its old path if renamed since.
    found = {path: _blob_at(git_dir, commit, path) for path in paths}
    if any(blob is None for blob in found.values()):
        renamed = _renamed_since(git_dir, commit)
        for path, blob in found.items():
            if blob is None and path in renamed:
                found[path] = _blob_at(git_dir, commit, renamed[path])
    if missing := [path for path, blob in found.items() if blob is None]:
        msg = (
            f"not in {at}: {', '.join(missing)}: leave out the files that commit "
            "doesn't have"
        )
        raise ReviewError(msg)
    return {path: blob for path, blob in found.items() if blob is not None}


def _renamed_since(git_dir: Path, commit: str) -> dict[str, str]:
    # The files renamed between `commit` and HEAD: each new path's old one.
    out = _git(git_dir, "diff", "-M", "--name-status", "-z", commit, "HEAD") or ""
    fields = out.split("\0")
    renamed, position = {}, 0
    while position < len(fields) and fields[position]:
        status = fields[position]
        if status[:1] in ("R", "C") and position + 2 < len(fields):
            renamed[fields[position + 2]] = fields[position + 1]
            position += 3
        else:
            position += 2
    return renamed


def _mark_targets(
    settings: "GlobalSettings",
    paths: Sequence[Path],
    recorded: Mapping[str, str],
    deck: str | None,
    accepted: set[str],
    forget: Sequence[Path],
) -> list[str]:
    # What `mark` records: the files `paths` stand for; with none, every
    # file the report records (and a deck's own files), unless `--accept`
    # or `--forget` is given: alone, they touch only what they name, since
    # refreshing every file then would mark changes nobody read.
    if paths:
        targets = _targets(settings, paths, deck)
    elif accepted or forget:
        targets = []
    else:
        own = deck_own_files(settings, deck) if deck is not None else []
        targets = list(dict.fromkeys([*recorded, *own]))
    return targets + [path for path in sorted(accepted) if path not in targets]


def _targets(
    settings: "GlobalSettings", paths: Sequence[Path], deck: str | None
) -> list[str]:
    # The files `paths` stand for (`expand`); in a deck's report, the deck's
    # directory stands for its own files rather than its content.
    if deck is None:
        return expand(settings, paths)
    root = settings.paths.git_dir / deck
    found: dict[str, None] = {}
    for path in paths:
        chosen = (
            deck_own_files(settings, deck) if path == root else expand(settings, [path])
        )
        found.update(dict.fromkeys(chosen))
    return list(found)


def _shared_content(
    settings: "GlobalSettings", targets: Iterable[str], deck: str | None, report: str
) -> list[tuple[str, str]]:
    # In a deck's report, the shared content files among `targets`, each
    # with why it's refused.
    if deck is None:
        return []
    content_dir = settings.paths.content_dir
    sections = _rel(settings, review_dir(settings)) + f"/{SECTIONS_DIR}/"
    return [
        (
            path,
            f"{path}: shared content, which a deck's report doesn't record: review "
            f"it in its section's report (under {sections}); `deckz review mark "
            f"{report}` with no path records the deck's own files",
        )
        for path in targets
        if (settings.paths.git_dir / path).is_relative_to(content_dir)
    ]


def _mark_at(
    settings: "GlobalSettings",
    report: Path,
    at: str,
    paths: Sequence[Path],
    existing: Report,
    deck: str | None,
    *,
    created: bool,
) -> MarkResult:
    # `mark --at`: record a past commit's versions of files the report
    # doesn't record yet.
    git_dir = settings.paths.git_dir
    rel_report = _rel(settings, report)
    commit = _git(git_dir, "rev-parse", "--verify", "--quiet", f"{at}^{{commit}}")
    if not commit:
        msg = f"{at} is not a commit: give the commit the review read (`git log`)"
        raise ReviewError(msg)
    commit = commit.strip()
    if _git(git_dir, "merge-base", "--is-ancestor", commit, "HEAD") is None:
        msg = (
            f"{at} is not in this branch's history: give a commit HEAD descends "
            "from, the one the review read"
        )
        raise ReviewError(msg)
    if paths:
        targets = _targets(settings, paths, deck)
    elif deck is not None:
        targets = deck_own_files(settings, deck, at=commit)
    else:
        msg = (
            f"nothing to mark in {rel_report}: name the files reviewed "
            f"(`deckz review mark {rel_report} --at {at} <path>...`)"
        )
        raise ReviewError(msg)
    if refused := _shared_content(settings, targets, deck, rel_report):
        raise ReviewError("; ".join(reason for _, reason in refused))
    if already := [path for path in targets if path in existing.files]:
        msg = (
            f"{rel_report} already records {', '.join(already)}: --at registers "
            "a past review of files a report doesn't record yet; leave them out, "
            f"or, reviewed since, `deckz review mark {rel_report} <path>` records "
            "today's version"
        )
        raise ReviewError(msg)
    files = _blobs_at(git_dir, commit, targets, at)
    day = date.fromisoformat(
        (_git(git_dir, "show", "-s", "--format=%cs", commit) or "").strip()
    )
    if existing.date is None or existing.base is None:
        _write_report(report, day, commit, files)
    else:
        _write_report(
            report,
            existing.date,
            existing.base,
            {**existing.files, **files},
            {**existing.own, **dict.fromkeys(files, (day, commit))},
        )
    return MarkResult(rel_report, created, tuple(files))
