"""Commit message trailers, and the empty commits that record a decision.

deckz keeps no state of its own about history: what a commit settles
(`Lang-sync`, `Lang-synced`, `Lab-outputs-current`) is a trailer in its
message, read back when the history is walked.
"""

import re
from pathlib import Path

from .exceptions import DeckzError

_TRAILER_LINE = re.compile(r"^[A-Za-z][\w-]*:\s?.*$")


def trailer_lines(message: str) -> list[tuple[str, str]]:
    """The trailers of a commit message's last paragraph, in order.

    That's its body, not the subject line.

    Returns:
        Each trailer's key and value, or `[]` if the body's last paragraph \
        isn't trailer-shaped (every line `Key: value`).
    """
    _subject, _, body = message.partition("\n")
    body = body.strip()
    if not body:
        return []
    paragraphs = re.split(r"\n\n+", body)
    lines = [line for line in paragraphs[-1].splitlines() if line.strip()]
    if not lines or not all(_TRAILER_LINE.match(line) for line in lines):
        return []
    found = []
    for line in lines:
        key, _, value = line.partition(":")
        found.append((key.strip(), value.strip()))
    return found


def trailer_values(message: str, key: str) -> list[str]:
    """The values of a commit message's `key` trailers.

    Returns:
        Each one, in order.
    """
    return [value for found, value in trailer_lines(message) if found == key]


def commit_empty(git_dir: Path, message: str) -> str:
    """Commit nothing but `message`, whatever is staged.

    Returns:
        The new commit's sha.

    Raises:
        DeckzError: If git refuses the commit.
    """
    from subprocess import run

    # `--only` with no path commits none of what's staged. `--no-verify`: the
    # commit changes no file, so the pre-commit hook would only check HEAD's
    # tree again (seconds, and failing on problems that aren't this commit's),
    # and the commit-msg hook's rule is about files changed.
    result = run(
        [
            "git",
            "commit",
            "--allow-empty",
            "--only",
            "--no-verify",
            "--cleanup=whitespace",
            "--file=-",
        ],
        cwd=git_dir,
        input=message,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        msg = f"git commit: {(result.stderr or result.stdout).strip()}"
        raise DeckzError(msg)
    return run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
