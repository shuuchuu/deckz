from pathlib import Path

from . import app


@app.command(name="variables")
def check_variables(*, en: bool = False, workdir: Path = Path()) -> None:
    """Report `variables.xxx` usage gaps across every shared flavor and every deck.

    Walks every shared section's every named flavor -- not just the ones \
    some deck currently uses -- plus every real deck's own tree, resolving \
    `variables` the same way a real build would (deck-wide `variables.yml`, \
    then each matched flavor's own `variables`, cascaded down to nested \
    includes). Reports:

    - UNDEFINED <fragment> <name>: a fragment reads `variables.<name>` (or \
        `variables['<name>']`) but nothing resolved at that point sets it.
    - UNUSED <section_yml> <name>: a section's `variables_to_define` \
        declares <name> but no fragment reachable under it, in any flavor, \
        ever reads it.
    - UNPARSABLE <fragment> <error>: a fragment fails to parse with the \
        target repo's own Jinja environment.
    - STRUCTURAL <context> <error>: a flavor/deck fails to parse at all \
        (commonly a flavor missing a `variables_to_define` entry, or one \
        with a value outside its `allowed_values`) -- the detailed tree is \
        printed to stderr, same as any other parsing failure.

    Args:
        en: Analyze the English variant
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit

    from ...analyzing.variables_usage import check_variables as _check_variables
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    report = _check_variables(settings, lang="en" if en else "fr")

    for fragment, name in report.undefined:
        print(f"UNDEFINED\t{fragment}\t{name}")
    for yml_path, name in report.unused:
        print(f"UNUSED\t{yml_path}\t{name}")
    for fragment, error in report.unparsable:
        print(f"UNPARSABLE\t{fragment}\t{error}")
    for context, error in report.structural:
        print(f"STRUCTURAL\t{context}\t{error}")

    if report.undefined or report.unused or report.unparsable or report.structural:
        sys_exit(1)
