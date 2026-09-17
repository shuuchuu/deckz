from pathlib import Path

from ...models import FlavorName
from . import app


@app.command()
def section_files(section: str, flavor: str, /, *, workdir: Path = Path()) -> None:
    """Print the files a shared section+flavor resolves to.

    Recurses into subsections, exactly like deckz would when building a deck \
    that includes $<SECTION>@<FLAVOR>. Prints one resolved absolute path per \
    line, sorted. Fails loudly if FLAVOR does not exist for SECTION.

    Args:
        section: Shared/latex-relative section id, e.g. python/basics
        flavor: Flavor name to resolve
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_analyzer import section_files as compute
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    for path in sorted(
        compute(
            settings.paths.shared_latex_dir,
            settings.file_extension,
            section,
            FlavorName(flavor),
        )
    ):
        print(path)
