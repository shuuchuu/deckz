from pathlib import Path

from . import app
from ._groups import SETUP


@app.command(group=SETUP)
def setup(
    *,
    check: bool = False,
    force: bool = False,
    videos: bool = False,
    claude: bool = False,
    workdir: Path = Path(),
) -> None:
    """Set up a clone of the repository: run it once, and again after pulling.

    Checks deckz's executables (git, pandoc) and those `deckz.yml` lists in
    `setup.requires`, saying how to install a missing one; installs the git
    hooks; runs the repository's own `setup.steps` not done yet; and
    reports the videos never rendered. Safe to run any number of times.
    Exits 1 while something is still missing or failed.

    Args:
        check: Only report, change nothing
        force: Also run the steps already done
        videos: Render the videos never rendered (slow), instead of only
            reporting them
        claude: Also install deckz's Claude Code hooks, for those who use it
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 while something is missing or failed.
    """
    from ..configuring.settings import GlobalSettings
    from ..setting_up import incomplete
    from ..setting_up import setup as _setup
    from ._presentation import RichProgress, print_setup

    items = _setup(
        GlobalSettings.from_yaml(workdir),
        check=check,
        force=force,
        videos=videos,
        claude=claude,
        progress=RichProgress(),
    )
    print_setup(items)
    if incomplete(items):
        raise SystemExit(1)
