from pathlib import Path

from . import app
from ._groups import EVERYDAY


@app.command(group=EVERYDAY)
def status(
    deck: Path | None = None,
    /,
    *,
    since: str | None = None,
    fetch: bool = False,
    checks: bool = True,
    decks: bool = True,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Where your work stands: what to do before committing, teaching or publishing.

    Your changes are the working tree's plus the commits not on the
    upstream branch yet (or since SINCE). Lists the content checks'
    problems, what your changes leave to translate (and the repository's
    backlog), lab notebooks and videos not published as committed or
    rendered, and the built PDFs of the decks your changes reach that
    don't match them. Every item says how to resolve it.

    With DECK, a deck's directory, what's left before teaching or
    uploading that deck instead, whoever made it: the checks' problems in
    its files (deferred ones included), its files waiting for a port to the
    other language, and its built PDFs not matching its content, with
    their shrunk frames and wrapping lines.

    Args:
        deck: Report on this deck only
        since: Count your changes from this revision (e.g. `HEAD~5`, a
            date's commit) instead of the upstream's merge base
        fetch: Fetch the labs and videos remotes first, instead of
            comparing with them as last fetched
        checks: Run the content checks (about 15 s on a large repository)
        decks: Compare the built PDFs of the decks your changes reach with
            their content (several seconds when a change reaches many)
        json: Print one JSON object instead
        workdir: Path to move into before running the command

    Raises:
        DeckzError: If DECK comes with --since or --fetch.
    """
    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..exceptions import DeckzError
    from ..status import deck_status
    from ..status import status as _status

    if deck is None:
        scope, sections = _status(
            GlobalSettings.from_yaml(workdir),
            since=since,
            fetch=fetch,
            checks=checks,
            decks=decks,
        )
    elif since is not None or fetch:
        msg = "--since and --fetch are about your changes, not one deck's: drop them"
        raise DeckzError(msg)
    else:
        scope, sections = deck_status(
            DeckSettings.from_yaml(workdir / deck), checks=checks, decks=decks
        )
    if json:
        from dataclasses import asdict

        from ._presentation import print_json

        print_json({"scope": scope, "sections": [asdict(s) for s in sections]})
        return
    from ._presentation import print_status

    print_status(scope, sections)
