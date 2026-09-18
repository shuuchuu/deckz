from pathlib import Path

from ...models import FlavorName
from . import app


@app.command()
def section_pair(section: str, flavor: str, /, *, workdir: Path = Path()) -> None:
    """Pair a shared section+flavor's resolved files with their en counterpart.

    Same idea as deck-pair, but for a bare section+flavor instead of a deck. \
    Prints a tab-separated line per resolved fr file: fr_path, expected \
    en_path, whether it exists on disk, and whether it is included by \
    <SECTION>/en/en.yml under FLAVOR (one of yes/no/no-en-yml/no-such-flavor).

    A "yes" only means an en/ file exists at the expected location and is \
    wired into the en flavor -- not that it faithfully translates the current \
    fr content. Read the actual files to confirm that.

    Args:
        section: Shared/latex-relative section id, e.g. python/basics
        flavor: Flavor name to resolve
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_analyzer import section_pair as compute
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    for pairing in compute(
        settings.paths.shared_latex_dir,
        settings.file_extensions,
        section,
        FlavorName(flavor),
    ):
        exists = "yes" if pairing.exists_on_disk else "no"
        print(f"{pairing.fr_path}\t{pairing.en_path}\t{exists}\t{pairing.included}")
