from pathlib import Path

from . import app
from ._groups import EVERYDAY


@app.command(group=EVERYDAY)
def status(
    *,
    since: str | None = None,
    fetch: bool = False,
    checks: bool = True,
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

    Args:
        since: Count your changes from this revision (e.g. `HEAD~5`, a
            date's commit) instead of the upstream's merge base
        fetch: Fetch the labs and videos remotes first, instead of
            comparing with them as last fetched
        checks: Run the content checks (about 15 s on a large repository)
        json: Print one JSON object instead
        workdir: Path to move into before running the command
    """
    from ..configuring.settings import GlobalSettings
    from ..status import status as _status

    scope, sections = _status(
        GlobalSettings.from_yaml(workdir), since=since, fetch=fetch, checks=checks
    )
    if json:
        from dataclasses import asdict

        from ._presentation import print_json

        print_json({"scope": scope, "sections": [asdict(s) for s in sections]})
        return
    from ._presentation import print_status

    print_status(scope, sections)
