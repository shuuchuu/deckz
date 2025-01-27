from pathlib import Path

from . import app


@app.command()
def upgrade(*, workdir: Path = Path()) -> None:
    """Transform a deckz repo to match the new conventions.

    Args:
        workdir: Path to move into before running the command.

    """
    from itertools import chain
    from shutil import move
    from sys import stderr

    from rich.console import Console

    from ..configuring.settings import GlobalSettings

    console = Console(file=stderr)
    old_settings = Path("settings.yml")
    if old_settings.exists():
        move(old_settings, "deckz.yml")

    settings = GlobalSettings.from_yaml(workdir)

    console.print("Renaming files (config -> variables, targets -> deck)")

    for old_path in chain(
        settings.paths.git_dir.rglob("global-variables.yml"),
        settings.paths.git_dir.rglob("company-variables.yml"),
        settings.paths.git_dir.rglob("deck-variables.yml"),
        (settings.paths.user_config_dir / "user-variables.yml",),
    ):
        new_path = old_path.parent / "variables.yml"
        if old_path.exists():
            move(old_path, new_path)
            console.print(
                "  :white_check_mark:"
                f"{old_path}\n"
                f"  → [link=file://{new_path}]{new_path}[/link]"
            )
