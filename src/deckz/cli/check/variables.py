from pathlib import Path

from .._options import Langs, unique
from . import app


@app.command(name="variables")
def check_variables(
    *, langs: Langs = ("fr",), json: bool = False, workdir: Path = Path()
) -> None:
    """Report `variables.xxx` usage gaps across every shared flavor and every deck.

    Walks every shared section's every named flavor -- not just the ones
    some deck currently uses -- with the repository-wide `variables.yml`,
    plus every real deck's own tree, with that deck's `variables.yml` files,
    as a real build would. Analyzes each language in turn, and reports,
    tagged with it:

    - `UNDEFINED <lang> <fragment> <name>`: a fragment reads
        `variables.<name>` (or `variables['<name>']`) but nothing sets it.
    - `UNPARSABLE <lang> <fragment> <error>`: a fragment fails to parse with
        the target repo's own Jinja environment.
    - `STRUCTURAL <lang> <context> <error>`: a flavor/deck fails to parse at
        all -- the detailed tree is printed to stderr, same as any other
        parsing failure. A shared flavor whose only failures are includes of
        deck-local files is skipped: the decks using it cover it.

    With --json, prints one JSON array of objects instead, each with a
    "kind" (undefined/unparsable/structural), its "lang" and the same
    fields: "fragment"/"context" and "name"/"error".

    Exits 1 when anything is reported.

    Args:
        langs: Languages to analyze
        json: Print the findings as JSON
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit

    from ...analyzing.variables_usage import check_variables as _check_variables
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    reports = [(lang, _check_variables(settings, lang=lang)) for lang in unique(langs)]

    if json:
        from .._presentation import print_json

        print_json(
            [
                item
                for lang, report in reports
                for item in (
                    *(
                        {
                            "kind": "undefined",
                            "lang": lang,
                            "fragment": fragment,
                            "name": name,
                        }
                        for fragment, name in report.undefined
                    ),
                    *(
                        {
                            "kind": "unparsable",
                            "lang": lang,
                            "fragment": fragment,
                            "error": error,
                        }
                        for fragment, error in report.unparsable
                    ),
                    *(
                        {
                            "kind": "structural",
                            "lang": lang,
                            "context": context,
                            "error": error,
                        }
                        for context, error in report.structural
                    ),
                )
            ]
        )
    else:
        for lang, report in reports:
            for fragment, name in report.undefined:
                print(f"UNDEFINED\t{lang}\t{fragment}\t{name}")
            for fragment, error in report.unparsable:
                print(f"UNPARSABLE\t{lang}\t{fragment}\t{error}")
            for context, error in report.structural:
                print(f"STRUCTURAL\t{lang}\t{context}\t{error}")

    if any(
        report.undefined or report.unparsable or report.structural
        for _, report in reports
    ):
        sys_exit(1)
