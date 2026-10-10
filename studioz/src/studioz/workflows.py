"""The workflows a repository declares for studioz, in its `deckz.yml`.

The section's reference is studioz's README, "Workflows".

A workflow is a form whose answers fill a prompt naming one of the
repository's skills, which starts a turn in the workspace's conversation:
the skill decides everything else, questions included, so a `prompt` holds
what to work on, never how (the plan's "Drift"). Inputs are `text` (a line),
`long-text` or `file`, which studioz keeps under the workspace's
`.run/studioz/fichiers/` and names by its path there.

The workspace's own `deckz.yml` declares them, read at each page: a branch
may add one with its skill. deckz ignores the section (its settings ignore
keys they don't know, which a deckz test keeps); its schema lives here, and
refuses unknown keys so that a typo shows instead of being dropped.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from deckz.exceptions import DeckzError
from deckz.utils import load_yaml

from .workspaces import STATE_DIR

FILES_DIR = STATE_DIR / "fichiers"
"""Where a workflow's files go, relative to the workspace (gitignored)."""

MAX_FILE_SIZE = 100 << 20

DECK = "deck"
"""The prompt's field for a `deck` workflow's deck."""

Text = str | dict[str, str]
"""A text shown to the person: one string, or one per language."""


def text(value: Text | None) -> str:
    """`value` in French, the UI's language, else in another one.

    Returns:
        The text, empty for None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.get("fr") or next(iter(value.values()), "")


_NAME = r"^[a-z_][a-z0-9_]*$"


class Input(BaseModel):
    """A field of a workflow's form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(pattern=_NAME)]
    """Its `{name}` in the prompt."""
    label: Text
    kind: Literal["text", "long-text", "file"] = "text"
    required: bool = True
    accept: str | None = None
    """For a file: the types offered, as HTML's `accept` (`.pdf,.md`)."""


class Workflow(BaseModel):
    """A workflow, as declared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Text
    skill: Annotated[str, Field(pattern=r"^[A-Za-z0-9][\w.-]*$")]
    prompt: Annotated[str, Field(min_length=1)]
    description: Text | None = None
    scope: Literal["workspace", "deck"] = "workspace"
    """`deck`: about one deck, chosen in the form or the deck on screen."""
    inputs: tuple[Input, ...] = ()

    @model_validator(mode="after")
    def _fields(self) -> Self:
        names = [one.name for one in self.inputs]
        if len(set(names)) != len(names):
            msg = "deux champs (`inputs`) ont le même nom"
            raise ValueError(msg)
        if DECK in names:
            msg = f"`{DECK}` est le champ de la formation, pas un nom de champ"
            raise ValueError(msg)
        known = {*names, *([DECK] if self.scope == "deck" else [])}
        try:
            used = {name for _, name, _, _ in Formatter().parse(self.prompt) if name}
        except ValueError as error:
            msg = f"prompt : {error} (une accolade s'écrit deux fois : {{{{)"
            raise ValueError(msg) from None
        if unknown := sorted(used - known):
            msg = f"le {{{unknown[0]}}} du prompt n'est aucun champ" + (
                " (`{deck}` demande `scope: deck`)" if unknown[0] == DECK else ""
            )
            raise ValueError(msg)
        return self

    @property
    def title(self) -> str:
        return text(self.name)

    @property
    def key(self) -> str:
        """Its name in URLs."""
        return re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-") or "workflow"

    def preview(self, deck: str = "") -> str:
        """The prompt, each field shown by its label.

        Args:
            deck: The deck, when it's known.

        Returns:
            What the person reads before starting it.
        """
        labels = {one.name: f"[{text(one.label)}]" for one in self.inputs}
        labels[DECK] = deck or "[Formation]"
        return self.prompt.format_map(labels)

    def refusal(
        self, values: dict[str, str], files: set[str], deck: str, decks: list[str]
    ) -> str | None:
        """What the form lacks to start this workflow.

        Args:
            values: The text fields' answers.
            files: The file fields given.
            deck: The deck chosen.
            decks: The workspace's decks.

        Returns:
            What to fill in, None if nothing.
        """
        if self.scope == "deck" and deck not in decks:
            return "Choisissez la formation."
        for one in self.inputs:
            if one.required and not (values.get(one.name) or one.name in files):
                return f"Remplissez « {text(one.label)} »."
        return None

    def message(self, values: dict[str, str]) -> tuple[str, str]:
        """The turn this workflow starts with `values`.

        Args:
            values: Each field's value (a file's path in the workspace).

        Returns:
            What the agent receives, naming the skill, and what the \
            transcript shows.
        """
        asked = self.prompt.format_map(
            {one.name: values.get(one.name, "") for one in self.inputs}
            | {DECK: values.get(DECK, "")}
        ).strip()
        return (
            f"Suis la skill `{self.skill}` du dépôt pour cette demande.\n\n{asked}",
            f"{self.title} : {asked}",
        )


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflows: tuple[Workflow, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> Self:
        keys = [workflow.key for workflow in self.workflows]
        if twice := sorted({key for key in keys if keys.count(key) > 1}):
            msg = f"deux workflows s'appellent « {twice[0]} »"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class Declared:
    """A workspace's workflows."""

    workflows: tuple[Workflow, ...] = ()
    error: str | None = None
    """Why its `deckz.yml`'s section can't be read: then there's none."""
    missing: dict[str, str] = field(default_factory=dict)
    """The workflows (by key) whose skill the workspace lacks, with the skill."""

    def get(self, key: str) -> Workflow | None:
        return next((w for w in self.workflows if w.key == key), None)

    def scoped(self, scope: str) -> list[Workflow]:
        return [workflow for workflow in self.workflows if workflow.scope == scope]


def skill_exists(workspace: Path, skill: str) -> bool:
    """Whether the workspace's project settings hold `skill`.

    Returns:
        Whether it's a skill (`.claude/skills/<skill>/SKILL.md`) or a \
        command (`.claude/commands/<skill>.md`) there.
    """
    claude = workspace / ".claude"
    return (claude / "skills" / skill / "SKILL.md").is_file() or (
        claude / "commands" / f"{skill}.md"
    ).is_file()


def declared(workspace: Path) -> Declared:
    """The workflows the workspace's `deckz.yml` declares.

    Returns:
        Them, or why the section is invalid.
    """
    path = workspace / "deckz.yml"
    if not path.is_file():
        return Declared()
    try:
        content = load_yaml(path)
    except DeckzError as error:
        return Declared(error=str(error))
    section = content.get("studioz") if isinstance(content, dict) else None
    if section is None:
        return Declared()
    try:
        parsed = _Section.model_validate(section)
    except ValidationError as error:
        problems = "\n".join(
            f"{'.'.join(['studioz', *(str(part) for part in found['loc'])])} : "
            f"{found['msg']}"
            for found in error.errors()
        )
        return Declared(error=problems)
    return Declared(
        parsed.workflows,
        missing={
            workflow.key: workflow.skill
            for workflow in parsed.workflows
            if not skill_exists(workspace, workflow.skill)
        },
    )


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", Path(filename.replace("\\", "/")).name)
    return name.strip(" .") or "fichier"


def keep_file(workspace: Path, filename: str, data: bytes) -> str:
    """Keep a file given to a workflow in the workspace.

    The same file given again is kept once; another one by the same name
    gets a number.

    Returns:
        Its path, relative to the workspace.

    Raises:
        OSError: When it can't be written, or 999 others have its name.
    """
    directory = workspace / FILES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(_safe_name(filename))
    for number in range(1, 1000):
        candidate = directory / (
            name.name if number == 1 else f"{name.stem}-{number}{name.suffix}"
        )
        if not candidate.exists():
            candidate.write_bytes(data)
            break
        if candidate.read_bytes() == data:
            break
    else:
        msg = f"trop de fichiers nommés {name.name}"
        raise OSError(msg)
    return candidate.relative_to(workspace).as_posix()
