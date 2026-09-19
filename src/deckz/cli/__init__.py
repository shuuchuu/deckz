from collections.abc import Iterable
from logging import INFO, basicConfig

from cyclopts import App
from rich.logging import RichHandler

from .. import __version__

app = App(version=__version__)
app.register_install_completion_command()


def main(args: Iterable[str] | None = None) -> None:
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)
    app(args, result_action="return_none")
