"""What a deck's and a workspace's buttons start: build, upload, publish.

Each runs as a job (`studioz.jobs`), by the workspace's own deckz with every
option spelled out (never a default from the person's `.env`), once the
person has seen what it does: what a build produces, the PDFs an upload
sends (and those deckz would refuse, `deckz upload --dry-run`), what a
publication replaces. deckz's own refusals still apply (outdated PDFs, a
published lab or video link that would disappear, uncommitted notebooks).
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from deckz.models import Lang

from .watches import workspace_environment

KINDS = {
    "handout": "Support (sans animations)",
    "presentation": "Présentation (avec animations)",
    "print": "Version à imprimer",
    "part-handouts": "Un support par partie, en plus",
    "html": "Page HTML (reveal.js)",
}
"""`deckz run`'s outputs, in French."""

DEFAULT_KINDS = frozenset({"handout", "presentation", "print"})

PUBLISHABLE = {
    "labs": (
        "les TP",
        "Les carnets du dernier commit de l'espace remplacent ceux que "
        "les stagiaires ouvrent depuis les PDF (Colab).",
    ),
    "videos": (
        "les vidéos",
        "Les rendus des scènes du dernier commit remplacent ceux "
        "que les QR codes des PDF ouvrent.",
    ),
}
"""What can be published, and what publishing does, in French."""

_PLAN_TIMEOUT = 300


def _deckz(workspace: Path) -> str:
    return str(workspace / ".venv" / "bin" / "deckz")


def build_steps(
    workspace: Path, kinds: frozenset[str], langs: list[Lang]
) -> list[list[str]]:
    """`deckz run` of a deck, every output named, on or off.

    Returns:
        The job's one step, to run in the deck's directory.
    """
    options = [f"--{kind}" if kind in kinds else f"--no-{kind}" for kind in KINDS]
    # `--sync` removes only what this build made obsolete (see `deckz run`).
    return [[_deckz(workspace), "run", *options, "--sync", "--lang", *langs]]


def build_title(deck: str, kinds: frozenset[str], langs: list[Lang]) -> str:
    names = ", ".join(
        KINDS[kind].split(" (")[0].lower() for kind in KINDS if kind in kinds
    )
    return f"Construire {deck} ({', '.join(langs)} : {names})"


@dataclass(frozen=True)
class UploadPlan:
    pdfs: tuple[str, ...]
    """The deck's PDFs, relative to the workspace."""
    outdated: tuple[str, ...]
    """Those that don't match the deck's content anymore: deckz refuses them."""
    error: str | None = None


def upload_plan(workspace: Path, deck: Path) -> UploadPlan:
    """What `deckz upload` would send from the deck, without connecting.

    Returns:
        Its PDFs and the outdated ones, or why deckz couldn't tell.
    """
    try:
        result = subprocess.run(
            [_deckz(workspace), "upload", "--dry-run", "--json"],
            cwd=deck,
            env=workspace_environment(workspace),
            capture_output=True,
            text=True,
            timeout=_PLAN_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return UploadPlan((), (), str(error))
    try:
        found = json.loads(result.stdout)
        return UploadPlan(tuple(found["pdfs"]), tuple(found["outdated"]))
    except (ValueError, KeyError, TypeError):
        lines = (result.stderr or result.stdout).strip().splitlines()
        error = lines[-1] if lines else f"code {result.returncode}"
        return UploadPlan((), (), error.replace(f"{workspace}/", ""))


def upload_steps(workspace: Path) -> list[list[str]]:
    """`deckz upload`, which refuses outdated PDFs itself.

    Returns:
        The job's one step, to run in the deck's directory.
    """
    return [[_deckz(workspace), "upload"]]


def publish_steps(workspace: Path, what: str) -> list[list[str]]:
    """`deckz labs publish` or `deckz videos publish`.

    Returns:
        The job's one step, to run in the workspace.

    Raises:
        ValueError: For anything but `PUBLISHABLE`.
    """
    if what not in PUBLISHABLE:
        msg = f"Rien à publier sous le nom « {what} »"
        raise ValueError(msg)
    return [[_deckz(workspace), what, "publish"]]
