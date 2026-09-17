from pathlib import Path

from .. import app


@app.command()
def deck_pair(*, workdir: Path = Path()) -> None:
    """Pair a fr deck's resolved files with their expected en counterpart.

    For each file the deck at WORKDIR resolves to, print a tab-separated line: \
    fr_path, expected en_path ("?" if fr_path is not under a known latex \
    root), whether en_path exists on disk, and whether it is actually included \
    by <WORKDIR>/en/deck.yml (one of yes/no/no-en-deck/unresolvable-root).

    A "yes" only means an en/ file exists at the expected location and is \
    wired into the en deck -- not that it faithfully translates the current fr \
    content. Read the actual files to confirm that.

    Args:
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_analyzer import deck_pair as compute_deck_pair
    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(workdir)
    for pairing in compute_deck_pair(settings):
        en_path = pairing.en_path if pairing.en_path is not None else "?"
        exists = "yes" if pairing.exists_on_disk else "no"
        print(f"{pairing.fr_path}\t{en_path}\t{exists}\t{pairing.included}")
