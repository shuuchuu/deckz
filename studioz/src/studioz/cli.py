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
def serve(
    *,
    workdir: Path = Path(),
    port: int = 8421,
    browser: bool = True,
    min_free_memory: float = 3.0,
    # `agent.DEFAULT_MODEL`, spelled out: importing the agent would load the
    # Agent SDK for `--help`.
    model: str = "sonnet",
) -> None:
    """Start studioz on this machine, for the repository of the current directory.

    Args:
        workdir: Any directory of the repository's checkouts
        port: Local port to listen on
        browser: Open studioz in the browser once it's ready
        min_free_memory: Gibibytes of memory a build or a render waits for
            before it starts (0: never waits); "Lancer quand même" starts it
        model: The agent's model, as Claude Code names it (`sonnet`, `opus`,
            or a model's id); a workflow may declare its own

    Raises:
        SystemExit: With code 1 outside a deckz repository.
    """
    import os

    import uvicorn

    from deckz.exceptions import DeckzError
    from deckz.utils import get_git_dir

    from . import memory
    from .agent import Agents
    from .app import create_app
    from .jobs import Jobs

    if os.environ.pop("ANTHROPIC_API_KEY", None) is not None:
        # The agent works on the person's own Claude account (plan,
        # "Credentials"): a key left in the shell would bill it instead.
        print("studioz: ANTHROPIC_API_KEY ignoré, l'agent utilise votre compte Claude")
    min_free = int(min_free_memory * memory.GIB)
    if min_free and memory.read() is not None:
        print(
            f"studioz: constructions et rendus en attente sous {memory.gib(min_free)}"
            " de mémoire disponible (--min-free-memory)"
        )
    try:
        application = create_app(
            get_git_dir(workdir.resolve()),
            jobs=Jobs(min_free=min_free),
            agents=Agents(model=model),
        )
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
        SystemExit: With code 1 when Claude Code isn't logged in afterwards.
    """
    import subprocess

    from .agent import LOGIN, claude_cli, logged_in

    subprocess.call([claude_cli(), "auth", "login", "--claudeai"])
    # Claude Code may say "Login successful" after a wrong code: its status
    # says the truth.
    ok, account = logged_in()
    if not ok:
        print(f"studioz: {account} ; relancez « {LOGIN} ».")
        raise SystemExit(1)
    who = f" ({account})" if account else ""
    print(f"studioz: l'agent utilise votre compte Claude{who}.")


def _open_when(started: Callable[[], bool], url: str) -> None:
    for _ in range(100):
        if started():
            webbrowser.open(url)
            return
        sleep(0.1)


def main() -> None:
    app()
