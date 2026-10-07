"""Write deckz's git hooks into a repository's `.git/hooks/`.

Each installed hook is a thin shell script that shells back out to `deckz`:
the pre-commit hook runs `deckz check --staged` (so the checks apply to the
commit about to be made, not the unstaged working tree); the commit-msg
hook runs `deckz hooks check-commit-msg`, refusing a commit that changes
one side of a fr/en pair without a `Lang-sync` trailer (see
`deckz.analyzing.i18n_stale.staged_one_sided_pairs`).

A hook file deckz didn't write itself (no `_MARKER` line) is left alone
unless `force` is passed, so installing never silently clobbers a repo's
own pre-existing hook.
"""

from pathlib import Path

from .exceptions import HookInstallRefusedError

_MARKER = "# deckz-managed hook: safe to overwrite (deckz hooks install)"

HOOKS: dict[str, str] = {
    "pre-commit": f"#!/bin/sh\n{_MARKER}\nexec deckz check --staged\n",
    "commit-msg": f'#!/bin/sh\n{_MARKER}\nexec deckz hooks check-commit-msg "$1"\n',
}


def install_hooks(git_dir: Path, *, force: bool = False) -> list[Path]:
    """Write every hook in `HOOKS` into `git_dir`'s `.git/hooks/`.

    Args:
        git_dir: Root of the deckz-managed repository.
        force: Overwrite a hook file even if it isn't one deckz wrote.

    Returns:
        The written hook paths.

    Raises:
        HookInstallRefusedError: If an existing hook file doesn't carry \
            deckz's marker and `force` isn't set.
    """
    hooks_dir = git_dir / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in HOOKS.items():
        path = hooks_dir / name
        if (
            path.exists()
            and not force
            and _MARKER not in path.read_text(encoding="utf-8")
        ):
            msg = f"{path} already exists and isn't a deckz-managed hook"
            raise HookInstallRefusedError(msg)
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | 0o111)
        written.append(path)
    return written
