"""Where a person's work stands, and what's left to do: `deckz status`.

"Your changes" are the working tree's, plus the commits since `since`, or
else since the merge base with the branch's upstream (what isn't pushed
yet). Each section lists what needs doing, every item with the command or
edit that resolves it. Nothing here touches the network unless `fetch`:
the labs and videos are compared with their remotes as last fetched.
"""

import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

_MAX_ITEMS = 15


@dataclass(frozen=True)
class StatusItem:
    text: str
    fix: str = ""


@dataclass(frozen=True)
class StatusSection:
    title: str
    summary: str
    """One line: what was looked at, or that nothing needs doing."""
    items: tuple[StatusItem, ...] = field(default=())
    key: str = ""
    """What the section is about, for a program, whatever its title: `checks`, \
    `translation`, `labs`, `videos` or `decks`."""


def _git(git_dir: Path, *args: str, strip: bool = True) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(git_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.strip() if strip else result.stdout


def base_revision(git_dir: Path, since: str | None) -> tuple[str | None, str]:
    """The commit "your changes" start after, and how it was chosen.

    Returns:
        `(sha or None, description)`: None when there's no upstream to \
        compare with, then only the working tree counts.
    """
    if since:
        sha = _git(git_dir, "rev-parse", "--verify", f"{since}^{{commit}}")
        return sha, f"since {since}"
    upstream = _git(
        git_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    if not upstream:
        return None, "the working tree only (no upstream branch)"
    return _git(git_dir, "merge-base", "HEAD", upstream), f"not in {upstream} yet"


def changed_paths(git_dir: Path, base: str | None) -> tuple[set[str], set[str]]:
    """The files the working tree changes, and those changed since `base`.

    Returns:
        `(uncommitted, all)`: paths relative to `git_dir`.
    """
    # Not stripped: an entry starts with its two status columns, often a space.
    status = _git(
        git_dir, "status", "--porcelain=v1", "-z", "--untracked-files=all", strip=False
    )
    uncommitted = set()
    entries = (status or "").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        uncommitted.add(entry[3:])
        if entry[0] in "RC":  # A rename's or copy's source follows.
            index += 1
    committed = set()
    if base:
        diff = _git(git_dir, "diff", "--name-only", "-z", base, "HEAD") or ""
        committed = {path for path in diff.split("\0") if path}
    return uncommitted, uncommitted | committed


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _capped(items: Sequence[StatusItem]) -> tuple[StatusItem, ...]:
    if len(items) <= _MAX_ITEMS:
        return tuple(items)
    more = len(items) - _MAX_ITEMS
    return (*items[:_MAX_ITEMS], StatusItem(f"... and {more} more"))


def checks_section(settings: "GlobalSettings") -> StatusSection:
    """The content checks the pre-commit hook runs, on the working tree.

    Returns:
        Their section.
    """
    from .components.factory import GlobalSettingsFactory

    available = GlobalSettingsFactory(settings).checks_runner().checks()
    items = [
        StatusItem(f"{name}: {problem}")
        for name, check in available.items()
        if name not in settings.checks.opt_in
        for problem in check()
    ]
    summary = (
        f"{_count(len(items), 'problem')}: `deckz check` lists them"
        if items
        else "every check passes"
    )
    return StatusSection("Checks", summary, _capped(items))


def _commit_date(git_dir: Path, sha: str) -> str:
    return _git(git_dir, "show", "-s", "--format=%cs", sha) or "?"


def translation_section(
    settings: "GlobalSettings", uncommitted: set[str], changed: set[str]
) -> StatusSection:
    """What your changes leave to port to the other language, and the backlog.

    Returns:
        Its section.
    """
    from .analyzing.i18n_stale import content_pairs, notebook_pairs, stale_files

    git_dir = settings.paths.git_dir
    items = []
    for fr, en in [*content_pairs(settings), *notebook_pairs(settings)]:
        if (str(fr) in uncommitted) != (str(en) in uncommitted):
            edited, other = (fr, en) if str(fr) in uncommitted else (en, fr)
            items.append(
                StatusItem(
                    f"{edited}: changed without {other} (not committed yet)",
                    "port the change, or commit it with a Lang-sync trailer",
                )
            )
    every = stale_files(settings)
    yours = [stale for stale in every if str(stale.path) in changed]
    items += [
        StatusItem(
            f"{stale.path}: {_count(len(stale.commits), 'commit')} not ported to "
            f"{stale.sibling}",
            f"`deckz i18n stale {stale.path}` shows them",
        )
        for stale in yours
    ]
    if every:
        oldest = min(
            (_commit_date(git_dir, stale.commits[0].sha) for stale in every),
            default="?",
        )
        backlog = (
            f"{_count(len(every), 'file')} in the repository waiting for a port, "
            "the oldest "
            f"since {oldest} (`deckz i18n stale`)"
        )
    else:
        backlog = "nothing waits for a port in the repository"
    return StatusSection("Translation", backlog, _capped(items))


def labs_section(
    settings: "GlobalSettings", uncommitted: set[str], *, fetch: bool
) -> StatusSection:
    """Lab notebooks not committed, or committed but not published.

    Returns:
        Its section.
    """
    from .exceptions import LabPublishRefusedError
    from .labs.publishing import _published_notebooks

    git_dir = settings.paths.git_dir
    notebooks_dir = settings.paths.labs_notebooks_dir
    if not notebooks_dir.is_dir():
        return StatusSection("Labs", "no lab notebooks")
    labs = settings.labs
    notebooks_rel = notebooks_dir.relative_to(git_dir).as_posix()
    items = []
    if pending := sorted(p for p in uncommitted if p.startswith(notebooks_rel + "/")):
        items.append(
            StatusItem(
                f"{_count(len(pending), 'notebook')} with uncommitted changes",
                "commit them before publishing",
            )
        )
    if fetch:
        _git(git_dir, "fetch", "--quiet", labs.publish_remote, labs.publish_branch)
    ref = f"{labs.publish_remote}/{labs.publish_branch}"
    remote = _git(git_dir, "rev-parse", "--verify", "--quiet", ref)
    if remote is None:
        summary = f"{ref} was never fetched: `deckz status --fetch` compares with it"
        return StatusSection("Labs", summary, _capped(items))
    try:
        committed = _published_notebooks(
            git_dir,
            notebooks_dir,
            id_metadata_key=labs.id_metadata_key,
            id_pattern=labs.id_pattern,
            not_secrets=labs.not_secrets,
        )
    except LabPublishRefusedError as error:
        items.append(StatusItem(f"not publishable: {error}"))
        return StatusSection("Labs", "", _capped(items))
    published = {}
    for line in (_git(git_dir, "ls-tree", "-r", remote) or "").splitlines():
        info, name = line.split("\t", 1)
        published[name.removesuffix(".ipynb")] = info.split()[2]
    differ = sorted(lab for lab, sha in committed.items() if published.get(lab) != sha)
    if differ:
        shown = ", ".join(differ[:8]) + (", ..." if len(differ) > 8 else "")
        items.append(
            StatusItem(
                f"{_count(len(differ), 'committed notebook')} not as published: "
                f"{shown}",
                "`deckz labs publish`, once they're reviewed",
            )
        )
    summary = f"compared with {ref} as fetched on {_commit_date(git_dir, remote)}"
    return StatusSection("Labs", summary, _capped(items))


def videos_section(settings: "GlobalSettings", *, fetch: bool) -> StatusSection:
    """Videos never rendered, rendered as drafts, or not published as rendered.

    Returns:
        Its section.
    """
    from .videos import quality, renders, scenes
    from .videos.publishing import fetch_published, published_blobs, unpublished_reason

    git_dir = settings.paths.git_dir
    videos = settings.videos
    found = [
        r
        for scene in scenes(settings)
        for r in renders(settings.paths.videos_dir, scene)
    ]
    if not found:
        return StatusSection("Videos", "no videos")
    items = []
    missing = [r for r in found if not r.file.is_file()]
    if missing:
        items.append(
            StatusItem(
                f"{_count(len(missing), 'video')} never rendered",
                "`deckz videos render` (decks using them fail to build)",
            )
        )
    drafts = [
        r
        for r in found
        if r.file.is_file() and quality(r.file) != videos.published_quality
    ]
    if drafts:
        items.append(
            StatusItem(
                f"{_count(len(drafts), 'video')} rendered as drafts",
                "`deckz videos render` renders them at the published quality",
            )
        )
    ref = f"{videos.publish_remote}/{videos.publish_branch}"
    commit = (
        fetch_published(git_dir, videos.publish_remote, videos.publish_branch)
        if fetch
        else _git(git_dir, "rev-parse", "--verify", "--quiet", ref)
    )
    if commit is None:
        summary = f"{ref} was never fetched: `deckz status --fetch` compares with it"
        return StatusSection("Videos", summary, _capped(items))
    published = published_blobs(git_dir, commit)
    unpublished = [
        reason
        for r in found
        if r.file.is_file() and quality(r.file) == videos.published_quality
        if (
            reason := unpublished_reason(
                git_dir,
                settings.paths.videos_dir,
                r.file,
                published,
                wanted_quality=videos.published_quality,
            )
        )
    ]
    items += [
        StatusItem(reason, "`deckz videos publish`, once reviewed")
        for reason in unpublished
    ]
    summary = f"compared with {ref} as fetched on {_commit_date(git_dir, commit)}"
    return StatusSection("Videos", summary, _capped(items))


def decks_section(settings: "GlobalSettings", changed: Iterable[str]) -> StatusSection:
    """The built PDFs of the decks your changes reach that don't match them.

    Returns:
        Its section.
    """
    from .analyzing.affected import affected_decks
    from .models import LANGS, lang_dir
    from .pipelines import deck_targets, outdated_pdfs

    git_dir = settings.paths.git_dir
    decks = affected_decks(git_dir, [Path(path) for path in changed])
    if not decks:
        return StatusSection("Built decks", "your changes reach no deck")
    items = []
    for deck in decks:
        langs = [
            lang
            for lang in LANGS
            if any(lang_dir(deck.paths.pdf_dir, lang).glob("*.pdf"))
        ]
        if not langs:
            continue
        where = deck.paths.current_dir.relative_to(git_dir)
        outdated = outdated_pdfs(deck_targets(deck, langs))
        if outdated:
            items.append(
                StatusItem(
                    f"{where}: {_count(len(outdated), 'PDF')} not matching its content",
                    f"`deckz run --workdir {where}` with the kinds and languages "
                    "you hand out",
                )
            )
    names = ", ".join(str(d.paths.current_dir.relative_to(git_dir)) for d in decks[:6])
    more = f" and {len(decks) - 6} more" if len(decks) > 6 else ""
    summary = f"your changes reach {_count(len(decks), 'deck')}: {names}{more}"
    return StatusSection("Built decks", summary, _capped(items))


def status(
    settings: "GlobalSettings",
    *,
    since: str | None = None,
    fetch: bool = False,
    checks: bool = True,
    decks: bool = True,
) -> tuple[str, list[StatusSection]]:
    """Every section of `deckz status`.

    Args:
        settings: The repository's settings.
        since: Count your changes from this revision instead of the \
            upstream's merge base.
        fetch: Fetch the labs and videos remotes first.
        checks: Run the content checks (the slowest part).
        decks: Compare the built PDFs of the decks your changes reach with \
            their content (the next slowest).

    Returns:
        `(what "your changes" means, the sections)`.
    """
    git_dir = settings.paths.git_dir
    base, scope = base_revision(git_dir, since)
    uncommitted, changed = changed_paths(git_dir, base)
    sections = {"checks": checks_section(settings)} if checks else {}
    sections |= {
        "translation": translation_section(settings, uncommitted, changed),
        "labs": labs_section(settings, uncommitted, fetch=fetch),
        "videos": videos_section(settings, fetch=fetch),
    }
    if decks:
        sections["decks"] = decks_section(settings, changed)
    return f"{_count(len(changed), 'changed file')}, {scope}", [
        replace(section, key=key) for key, section in sections.items()
    ]
