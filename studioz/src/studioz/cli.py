"""The `studioz` command: serve the application and open it in the browser."""

import webbrowser
from collections.abc import Callable
from pathlib import Path
from threading import Thread
from time import sleep
from types import FrameType

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
    import os

    import uvicorn

    from deckz.exceptions import DeckzError
    from deckz.utils import get_git_dir

    from .app import create_app

    if os.environ.pop("ANTHROPIC_API_KEY", None) is not None:
        # The agent works on the person's own Claude account (plan,
        # "Credentials"): a key left in the shell would bill it instead.
        print("studioz: ANTHROPIC_API_KEY ignoré, l'agent utilise votre compte Claude")
    try:
        application = create_app(get_git_dir(workdir.resolve()))
    except DeckzError as error:
        print(f"studioz: {error}")
        raise SystemExit(1) from error
    studio = application.state.studio

    class Server(uvicorn.Server):
        def handle_exit(self, sig: int, frame: FrameType | None) -> None:
            # Ends the pages' server-sent events, which uvicorn would wait
            # for: the pages reconnect to the next studioz by themselves.
            studio.closing.set()
            super().handle_exit(sig, frame)

    server = Server(
        uvicorn.Config(
            application, host="127.0.0.1", port=port, timeout_graceful_shutdown=5
        )
    )
    url = f"http://localhost:{port}/"
    if browser:
        Thread(
            target=_open_when, args=(lambda: server.started, url), daemon=True
        ).start()
    print(f"studioz: {url} (Ctrl-C to stop)", flush=True)
    server.run()


@app.command
def login() -> None:
    """Log the agent's Claude Code in, with your Claude account.

    The agent then works on your Claude subscription; studioz never sees
    your credentials (Claude Code keeps them, as when run in a terminal).

    Raises:
        SystemExit: With Claude Code's exit code when it fails.
    """
    import subprocess

    from .agent import claude_cli

    code = subprocess.call([claude_cli(), "auth", "login", "--claudeai"])
    if code:
        raise SystemExit(code)


def _open_when(started: Callable[[], bool], url: str) -> None:
    for _ in range(100):
        if started():
            webbrowser.open(url)
            return
        sleep(0.1)


def main() -> None:
    app()
