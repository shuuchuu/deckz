from pathlib import Path

from . import app


@app.command
def stop(*, workdir: Path = Path()) -> None:
    """Ask the `deckz agent loop` running here to end after its current session.

    The session at work goes on to the end of its share (recorded, committed),
    then the loop starts no other: nothing is left half done, and the loop is
    started again later with the same command. A loop waiting for a usage
    limit ends within a minute instead, without reopening the session the
    limit cut: `deckz agent loop --resume <session id>` does, later.

    A loop runs in the repository it was started in: one started with
    --workdir (a worktree's) is stopped with the same --workdir. Removing the
    `stop` file this command names takes the request back.

    Args:
        workdir: Path to move into before running the command
    """
    from ...agent_loop import request_stop
    from ...utils import get_git_dir

    for log_dir in request_stop(get_git_dir(workdir.resolve())):
        print(f"asked to stop after its current session: {log_dir / 'stop'}")
