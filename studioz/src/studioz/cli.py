"""The `studioz` command: serve the application and open it in the browser."""

import webbrowser
from collections.abc import Callable
from pathlib import Path
from threading import Thread
from time import sleep

from cyclopts import App

app = App(name="studioz", help="Work on a deckz repository from the browser.")


@app.default
def serve(*, workdir: Path = Path(), port: int = 8421, browser: bool = True) -> None:
    """Start studioz on this machine, for the repository of the current directory.

    Args:
        workdir: Any directory of the repository's checkouts
        port: Local port to listen on
        browser: Open studioz in the browser once it's ready

    Raises:
        SystemExit: With code 1 outside a deckz repository.
    """
    import uvicorn

    from deckz.exceptions import DeckzError
    from deckz.utils import get_git_dir

    from .app import create_app

    try:
        application = create_app(get_git_dir(workdir.resolve()))
    except DeckzError as error:
        print(f"studioz: {error}")
        raise SystemExit(1) from error
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port))
    url = f"http://localhost:{port}/"
    if browser:
        Thread(
            target=_open_when, args=(lambda: server.started, url), daemon=True
        ).start()
    print(f"studioz: {url} (Ctrl-C to stop)", flush=True)
    server.run()


def _open_when(started: Callable[[], bool], url: str) -> None:
    for _ in range(100):
        if started():
            webbrowser.open(url)
            return
        sleep(0.1)


def main() -> None:
    app()
