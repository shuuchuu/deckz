from pathlib import Path

from ..models import PartName
from . import app


@app.command()
def run(
    parts: list[PartName] | None = None,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile the deck in WORKDIR.

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from ..configuring.settings import DeckSettings
    from ..pipelines import run

    run(
        settings=DeckSettings.from_yaml(workdir),
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        parts_whitelist=parts,
    )
