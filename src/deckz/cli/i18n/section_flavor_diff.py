from pathlib import Path

from . import app


@app.command()
def section_flavor_diff(section: str, /, *, workdir: Path = Path()) -> None:
    """Structurally compare a shared section's fr flavors against its en/en.yml.

    SECTION is a shared/latex-relative section id (e.g. python/basics). This \
    is a direct, cheap comparison of each flavor's normalized includes list -- \
    it does not resolve anything with deckz's engine, so it cannot catch an \
    absolute include that silently resolves to the wrong (fr) file while still \
    normalizing to a matching key on both sides; run section-en-leak \
    alongside it for that.

    Prints one finding per line, nothing if the section is fr/en-clean:

    - NO_FR_YML <path>: section has no fr yml (bug)
    - NO_EN_YML <path>: section has no en/en.yml at all
    - MISSING_FLAVOR <name>: flavor only in fr
    - EXTRA_FLAVOR <name>: flavor only in en
    - FLAVOR <name> MISSING <key> x<count>: entry only in fr's version of a \
        shared flavor
    - FLAVOR <name> EXTRA <key> x<count>: entry only in en's version of a \
        shared flavor

    Args:
        section: Shared/latex-relative section id, e.g. python/basics
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_analyzer import section_flavor_diff as compute
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    for finding in compute(settings.paths.shared_latex_dir, section):
        print(finding)
