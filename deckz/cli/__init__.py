from logging import INFO, basicConfig
from pathlib import Path

from rich.logging import RichHandler
from typer import Option, Typer
from typing_extensions import Annotated

from ..utils import import_module_and_submodules

app = Typer()


WorkdirOption = Annotated[
    Path, Option(help="Path to move into before running the command")
]
HandoutOption = Annotated[bool, Option(help="Produce PDFs without animations")]
PresentationOption = Annotated[bool, Option(help="Produce PDFs with animations")]
PrintOption = Annotated[bool, Option(help="Produce printable PDFs")]
TargetOption = Annotated[
    list[str], Option(help="Targets to compile", default_factory=list)
]


def main() -> None:
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    import_module_and_submodules(__name__)
    app()
