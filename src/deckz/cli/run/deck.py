from pathlib import Path

from ...models import PartName
from . import app


@app.command(name="deck")
@app.default
def run(
    *,
    parts: list[PartName] | None = None,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile the deck in WORKDIR (default).

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant. Every resolved file, title and \
            variable must have a complete English translation, or the build \
            fails immediately
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import DeckSettings
    from ...pipelines import run

    run(
        settings=DeckSettings.from_yaml(workdir),
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        parts_whitelist=parts,
    )
