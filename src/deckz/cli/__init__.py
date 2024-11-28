from logging import INFO, basicConfig

from cyclopts import App
from rich.logging import RichHandler

from ..utils import import_module_and_submodules

app = App()


def main() -> None:
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    import_module_and_submodules(__name__)
    app()
