from pathlib import Path

from . import app


@app.command()
def affected(
    paths: list[Path] | None = None,
    /,
    *,
    since: str | None = None,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Print the decks a change to PATHS reaches, one directory per line.

    A deck is reached by a file it resolves (an English file counts as its
    French sibling), or by any file under its own directory. Relative to
    the repository root.

    Args:
        paths: Changed files, relative to the current directory
        since: Also the files changed since this revision (a commit, a
            branch, `HEAD~3`), the working tree's included, as `deckz
            status --since` counts them
        json: Print one JSON array instead
        workdir: Path to move into before running the command
    """
    from ...analyzing.affected import affected_decks, affected_since
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    git_dir = settings.paths.git_dir
    found = affected_decks(git_dir, [path.resolve() for path in paths or ()])
    if since is not None:
        seen = {deck.paths.current_dir for deck in found}
        found += [
            deck
            for deck in affected_since(git_dir, since)
            if deck.paths.current_dir not in seen
        ]
        found.sort(key=lambda deck: deck.paths.current_dir)
    decks = [str(deck.paths.current_dir.relative_to(git_dir)) for deck in found]
    if json:
        from .._presentation import print_json

        print_json(decks)
        return
    for deck in decks:
        print(deck)
