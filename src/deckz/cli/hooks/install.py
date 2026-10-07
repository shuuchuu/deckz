from pathlib import Path

from . import app


@app.command()
def install(*, force: bool = False, workdir: Path = Path()) -> None:
    """Install deckz's pre-commit and commit-msg git hooks.

    The pre-commit hook runs `deckz check --staged`; the commit-msg hook
    runs `deckz hooks check-commit-msg`, refusing a commit that changes one
    side of a fr/en content or notebook pair with no `Lang-sync` trailer.
    Refuses to overwrite a hook file that isn't one deckz itself wrote,
    unless `force` is passed.

    Args:
        force: Overwrite an existing hook even if it isn't deckz's own
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...hooks_install import install_hooks

    settings = GlobalSettings.from_yaml(workdir)
    for path in install_hooks(settings.paths.git_dir, force=force):
        print(path)
