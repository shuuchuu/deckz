from pathlib import Path

from . import app


@app.command()
def section_flavors(section: str, /, *, workdir: Path = Path()) -> None:
    """Print a shared section's flavor names, one per line.

    Reads only <SECTION>'s own yml (no resolution, no repo-wide scan) -- \
    useful to check a flavor exists before referencing it in a deck.yml, \
    without opening the yml file itself.

    Args:
        section: Shared/latex-relative section id, e.g. python/basics
        workdir: Path to move into before running the command

    """
    from ..analyzing.sections_search import flavor_names
    from ..configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    section_dir = settings.paths.latex_dir / section
    yml_path = section_dir / f"{section_dir.name}.yml"
    for name in flavor_names(yml_path):
        print(name)
