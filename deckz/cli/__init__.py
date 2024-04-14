from logging import INFO, basicConfig

from rich.logging import RichHandler
from typer import Option, Typer

from ..utils import import_module_and_submodules

app = Typer()


WorkdirOption = Option(help="Path to move into before running the command")
HandoutOption = Option(help="Produce PDFs without animations")
PresentationOption = Option(help="Produce PDFs with animations")
PrintOption = Option(help="Produce printable PDFs")


def main() -> None:
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    import_module_and_submodules(__name__)
    app()
