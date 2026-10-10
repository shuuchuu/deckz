"""Set up a clone of a deckz-managed repository: what `deckz setup` does.

Every step is idempotent and reports what it found or did as a
[`SetupItem`][deckz.setting_up.SetupItem]: deckz's own executables (git,
pandoc), those the repository declares (`deckz.yml`'s `setup.requires`), the
git hooks, the repository's own steps (`setup.steps`), and the videos a deck
build needs rendered. With `check`, nothing is changed: each item only says
what's missing, and how to fix it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from shutil import which
from subprocess import run
from typing import TYPE_CHECKING

from .hooks_install import HOOKS, hooks_dir, install_claude_hooks, install_hooks

if TYPE_CHECKING:
    from .components.protocols import ProgressReporterProtocol
    from .configuring.settings import GlobalSettings, SetupRequirement


class Status(Enum):
    OK = "ok"
    """Already in place."""
    DONE = "done"
    """Done by this run."""
    MISSING = "missing"
    """Not in place, and not done (`check`, or something a person must do)."""
    FAILED = "failed"
    """Tried, and failed."""


@dataclass(frozen=True)
class SetupItem:
    name: str
    status: Status
    detail: str = ""
    """What's missing or failed and how to fix it, or what was done."""


def setup(
    settings: "GlobalSettings",
    *,
    check: bool = False,
    force: bool = False,
    videos: bool = False,
    claude: bool = False,
    progress: "ProgressReporterProtocol | None" = None,
) -> list[SetupItem]:
    """Check, and unless `check`, set up everything a clone needs.

    Args:
        settings: The repository's settings.
        check: Only report, change nothing.
        force: Run the steps whose `creates` path already exists too.
        videos: Render the videos never rendered (otherwise only reported).
        claude: Also add deckz's Claude Code hooks to `.claude/settings.json`.
        progress: Advanced while rendering videos.

    Returns:
        One item per requirement, hook set, step and the videos.
    """
    items = requirements(settings)
    items.append(git_hooks(settings, check=check))
    if claude:
        items.append(claude_hooks(settings, check=check))
    items.extend(steps(settings, check=check, force=force))
    items.append(
        rendered_videos(settings, render=videos and not check, progress=progress)
    )
    return items


def _requirement(requirement: "SetupRequirement") -> SetupItem:
    if which(requirement.command):
        return SetupItem(requirement.command, Status.OK)
    detail = f"needed for {requirement.why}"
    if requirement.install:
        detail += f"; install it: {requirement.install}"
    return SetupItem(requirement.command, Status.MISSING, detail)


def requirements(settings: "GlobalSettings") -> list[SetupItem]:
    """The executables deckz needs, then the repository's `setup.requires`.

    Returns:
        One item per executable.
    """
    from .configuring.settings import SetupRequirement

    pandoc = settings.pandoc_command[0] if settings.pandoc_command else "pandoc"
    own = (
        SetupRequirement(command="git", why="deckz itself", install="apt install git"),
        SetupRequirement(
            command=pandoc,
            why="converting the Markdown content",
            install="apt install pandoc, or a release from github.com/jgm/pandoc",
        ),
    )
    return [_requirement(r) for r in (*own, *settings.setup.requires)]


def git_hooks(settings: "GlobalSettings", *, check: bool) -> SetupItem:
    """The pre-commit and commit-msg hooks `deckz hooks install` writes.

    Returns:
        Their item.
    """
    from .exceptions import HookInstallRefusedError

    git_dir = settings.paths.git_dir
    directory = hooks_dir(git_dir)
    stale = [
        name
        for name, body in HOOKS.items()
        if not (directory / name).is_file()
        or (directory / name).read_text(encoding="utf-8") != body
    ]
    if not stale:
        return SetupItem("git hooks", Status.OK)
    if check:
        return SetupItem(
            "git hooks",
            Status.MISSING,
            f"{', '.join(stale)} missing or outdated in {directory}: run `deckz setup`",
        )
    try:
        install_hooks(git_dir)
    except HookInstallRefusedError as error:
        return SetupItem(
            "git hooks",
            Status.FAILED,
            f"{error}: keep yours, or replace it with `deckz hooks install --force`",
        )
    return SetupItem("git hooks", Status.DONE, f"installed in {directory}")


def claude_hooks(settings: "GlobalSettings", *, check: bool) -> SetupItem:
    """The Claude Code hooks deckz provides, for those who work with Claude Code.

    Returns:
        Their item.
    """
    path = settings.paths.git_dir / ".claude" / "settings.json"
    if check:
        present = path.is_file() and "deckz" in path.read_text(encoding="utf-8")
        return SetupItem(
            "Claude Code hooks",
            Status.OK if present else Status.MISSING,
            "" if present else "run `deckz setup --claude`",
        )
    install_claude_hooks(settings.paths.git_dir)
    return SetupItem("Claude Code hooks", Status.DONE, f"in {path}")


def steps(settings: "GlobalSettings", *, check: bool, force: bool) -> list[SetupItem]:
    """The repository's own `setup.steps`, in order.

    Returns:
        One item per step.
    """
    git_dir = settings.paths.git_dir
    items = []
    for step in settings.setup.steps:
        if step.creates and (git_dir / step.creates).exists() and not force:
            items.append(SetupItem(step.name, Status.OK))
            continue
        command = " ".join(step.run)
        if check:
            items.append(
                SetupItem(step.name, Status.MISSING, f"run `deckz setup` ({command})")
            )
            continue
        if not which(step.run[0]):
            items.append(
                SetupItem(step.name, Status.FAILED, f"{step.run[0]} isn't installed")
            )
            continue
        result = run(step.run, cwd=git_dir, capture_output=True, text=True, check=False)
        if result.returncode:
            output = (result.stdout + result.stderr).strip()[-2000:]
            items.append(
                SetupItem(
                    step.name,
                    Status.FAILED,
                    f"`{command}` exited {result.returncode}:\n{output}",
                )
            )
        else:
            items.append(SetupItem(step.name, Status.DONE, f"ran `{command}`"))
    return items


def rendered_videos(
    settings: "GlobalSettings",
    *,
    render: bool,
    progress: "ProgressReporterProtocol | None" = None,
) -> SetupItem:
    """Whether every registered scene has its renders: a deck using one fails without.

    Only the renders that don't exist at all count; `deckz videos render` also \
    redoes outdated ones.

    Returns:
        Their item.
    """
    from .videos import renders, scenes

    missing = [
        r
        for scene in scenes(settings)
        for r in renders(settings.paths.videos_dir, scene)
        if not r.file.is_file()
    ]
    if not missing:
        return SetupItem("videos", Status.OK)
    if not render:
        return SetupItem(
            "videos",
            Status.MISSING,
            f"{len(missing)} never rendered, and decks using them fail to build: "
            "`deckz setup --videos` (or `deckz videos render`; slow at the "
            "published quality, `--quality l` for drafts)",
        )
    from .videos.rendering import render_all

    failed = render_all(
        missing, settings.videos.published_quality, settings.paths.scenes_dir, progress
    )
    if failed:
        return SetupItem("videos", Status.FAILED, "\n".join(failed))
    return SetupItem("videos", Status.DONE, f"rendered {len(missing)}")


def incomplete(items: Iterable[SetupItem]) -> bool:
    """Whether anything is still missing or failed.

    Returns:
        True if so.
    """
    return any(item.status in (Status.MISSING, Status.FAILED) for item in items)
