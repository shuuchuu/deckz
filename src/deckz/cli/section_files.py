from pathlib import Path

from ..models import FlavorName
from . import app


@app.command()
def section_files(
    section: str, flavor: str, /, *, en: bool = False, workdir: Path = Path()
) -> None:
    """Print the files a shared section+flavor resolves to.

    Recurses into subsections, exactly like deckz would when building a deck \
    that includes $<SECTION>@<FLAVOR>. Prints one resolved absolute path per \
    line, sorted. Fails loudly if FLAVOR does not exist for SECTION.

    Args:
        section: Shared/content-relative section id, e.g. python/basics
        flavor: Flavor name to resolve
        en: Resolve the English files, as `deckz run --en` would
        workdir: Path to move into before running the command

    """
    from ..analyzing.sections_search import section_files as compute
    from ..configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    for path in sorted(
        compute(
            settings,
            section,
            FlavorName(flavor),
            lang="en" if en else "fr",
        )
    ):
        print(path)
