from pathlib import Path

from . import app


@app.command()
def install(*, force: bool = False, ci: bool = False, workdir: Path = Path()) -> None:
    """Install deckz's git hooks and generic Claude Code hooks.

    The pre-commit hook runs `deckz check --staged`; the commit-msg hook
    runs `deckz hooks check-commit-msg`, marking a commit that changes one
    side of a fr/en content or notebook pair with no `Lang-sync` trailer
    `Lang-sync: pending`.
    Refuses to overwrite a git hook file that isn't one deckz itself wrote,
    unless `force` is passed.

    Also adds deckz's generic Claude Code hooks to `.claude/settings.json`
    (`deckz hooks pre-bash`/`pre-edit`/`post-edit`/`session-start`/`stop`,
    see `deckz.agent_hooks`): denying a Bash command that would stage
    everything or discard uncommitted work, checking an edited content
    file, and flagging a fr/en pair changed on one language side only, in
    a worktree or by the session's edits. With `deckz.yml`'s
    `worktree.required_for_agents`, they also keep agents from changing
    the main checkout (see `deckz.agent_checkouts`). Safe to call
    repeatedly: a hook deckz already registered gets the current command,
    timeout and matcher, every other key of the file untouched. A target
    repo's own `templates/hooks.py` (`GlobalPaths.hooks_module`) can add
    further Bash denials.

    Args:
        force: Overwrite an existing git hook (or with --ci, workflow) even
            if it isn't deckz's own
        ci: Also write `.github/workflows/deckz.yml`, a GitHub Actions
            workflow running `deckz check` and reading the `Lang-sync`
            trailers on every push and pull request (`deckz hooks
            check-commits`), and
            `deckz.yml`'s `ci.nightly_checks` every night: every
            contributor's commits get them, hooks installed or not
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...hooks_install import (
        install_ci_workflow,
        install_claude_hooks,
        install_hooks,
    )

    settings = GlobalSettings.from_yaml(workdir)
    for path in install_hooks(settings.paths.git_dir, force=force):
        print(path)
    print(install_claude_hooks(settings.paths.git_dir))
    if ci:
        print(install_ci_workflow(settings.paths.git_dir, settings.ci, force=force))
