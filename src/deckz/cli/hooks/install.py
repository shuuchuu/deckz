from pathlib import Path

from . import app


@app.command()
def install(*, force: bool = False, workdir: Path = Path()) -> None:
    """Install deckz's git hooks and generic Claude Code hooks.

    The pre-commit hook runs `deckz check --staged`; the commit-msg hook
    runs `deckz hooks check-commit-msg`, refusing a commit that changes one
    side of a fr/en content or notebook pair with no `Lang-sync` trailer.
    Refuses to overwrite a git hook file that isn't one deckz itself wrote,
    unless `force` is passed.

    Also adds deckz's generic Claude Code hooks to `.claude/settings.json`
    (`deckz hooks pre-bash`/`post-edit`/`session-start`/`stop`, see
    `deckz.agent_hooks`): denying a Bash command that would stage
    everything or discard uncommitted work, checking an edited content
    file, and flagging a fr/en pair changed on one language side only
    during the session. Safe to call repeatedly: an event deckz already
    registered is left as is, every other key of the file untouched. A
    target repo's own `templates/hooks.py` (`GlobalPaths.hooks_module`)
    can add further Bash denials.

    Args:
        force: Overwrite an existing git hook even if it isn't deckz's own
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...hooks_install import install_claude_hooks, install_hooks

    settings = GlobalSettings.from_yaml(workdir)
    for path in install_hooks(settings.paths.git_dir, force=force):
        print(path)
    print(install_claude_hooks(settings.paths.git_dir))
