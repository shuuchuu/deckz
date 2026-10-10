"""The workflows a repository declares for studioz, in its `deckz.yml`.

The section's reference is studioz's README, "Workflows".

A workflow is a form whose answers fill a prompt naming one of the
repository's skills, which starts a turn in the workspace's conversation:
the skill decides everything else, questions included, so a `prompt` holds
what to work on, never how (the plan's "Drift"). Inputs are `text` (a line),
`long-text` or `file`, which studioz keeps under the workspace's
`.run/studioz/fichiers/` and names by its path there.

The workspace's own `deckz.yml` declares them, read at each page: a branch
may add one with its skill. The home page offers those of the main
checkout's `HEAD` (`declared_at`), which a new workspace starts from. deckz
ignores the section (its settings ignore keys they don't know, which a deckz
test keeps); its schema lives here, and refuses unknown keys so that a typo
shows instead of being dropped.
"""

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError, safe_load

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


def _fields(prompt: str) -> set[str]:
    """The fields `{name}` of a prompt.

    Returns:
        Their names.

    Raises:
        ValueError: If its braces don't parse.
    """
    try:
        return {name for _, name, _, _ in Formatter().parse(prompt) if name}
    except ValueError as error:
        msg = f"prompt : {error} (une accolade s'écrit deux fois : {{{{)"
        raise ValueError(msg) from None


CHOSEN = "chosen"
"""A follow-up's field: the findings ticked, as a Markdown list."""
REPORT = "report"
"""A follow-up's field: the report's path in the workspace."""


class Then(BaseModel):
    """What a workflow's report offers to do next with the findings ticked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Text
    skill: Annotated[str, Field(pattern=r"^[A-Za-z0-9][\w.-]*$")]
    prompt: Annotated[str, Field(min_length=1)]
    description: Text | None = None

    @property
    def title(self) -> str:
        return text(self.name)

    def message(self, values: dict[str, str]) -> tuple[str, str]:
        """The turn it starts.

        Args:
            values: `deck`, `chosen` and `report`.

        Returns:
            What the agent receives, naming the skill, and what the \
            transcript shows.
        """
        asked = self.prompt.format_map(
            {name: values.get(name, "") for name in (DECK, CHOSEN, REPORT)}
        ).strip()
        return (
            f"Suis la skill `{self.skill}` du dépôt pour cette demande.\n\n{asked}",
            f"{self.title} : {asked}",
        )


def report_instruction(path: str) -> str:
    """What a workflow with a report asks besides its prompt.

    The checklist's format is studioz's (it reads it back), not the skill's.

    Returns:
        The instruction, in French.
    """
    return (
        f"Quand tu as fini, écris aussi tes constats dans `{path}` (même si la "
        "méthode suivie ne modifie aucun fichier par ailleurs), pour que la "
        "personne y choisisse ceux à traiter : un titre `## ` par catégorie, "
        "puis un constat par case à cocher (`- [ ] …`), chacun compréhensible "
        "seul (fichier, cadre ou cellule, le problème, ce que tu proposes), en "
        "Markdown, sans rien d'autre que de courtes remarques sous les titres."
    )


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
    report: bool = False
    """Whether the agent writes its findings as a checklist (`Report`)."""
    then: Then | None = None
    """What to do with the findings ticked in the report."""

    @model_validator(mode="after")
    def _fields(self) -> Self:
        names = [one.name for one in self.inputs]
        if len(set(names)) != len(names):
            msg = "deux champs (`inputs`) ont le même nom"
            raise ValueError(msg)
        if DECK in names:
            msg = f"`{DECK}` est le champ de la formation, pas un nom de champ"
            raise ValueError(msg)
        scoped = [DECK] if self.scope == "deck" else []
        if unknown := sorted(_fields(self.prompt) - {*names, *scoped}):
            msg = f"le {{{unknown[0]}}} du prompt n'est aucun champ" + (
                " (`{deck}` demande `scope: deck`)" if unknown[0] == DECK else ""
            )
            raise ValueError(msg)
        if self.then is not None:
            if not self.report:
                msg = "`then` demande `report: true` (ses constats à cocher)"
                raise ValueError(msg)
            allowed = {CHOSEN, REPORT, *scoped}
            if unknown := sorted(_fields(self.then.prompt) - allowed):
                msg = (
                    f"le {{{unknown[0]}}} du prompt de `then` n'est aucun champ "
                    f"({', '.join(f'{{{n}}}' for n in sorted(allowed))})"
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

    def message(
        self, values: dict[str, str], report: str | None = None
    ) -> tuple[str, str]:
        """The turn this workflow starts with `values`.

        Args:
            values: Each field's value (a file's path in the workspace).
            report: Where its report goes, if it has one.

        Returns:
            What the agent receives, naming the skill, and what the \
            transcript shows.
        """
        asked = self.prompt.format_map(
            {one.name: values.get(one.name, "") for one in self.inputs}
            | {DECK: values.get(DECK, "")}
        ).strip()
        told = f"Suis la skill `{self.skill}` du dépôt pour cette demande.\n\n{asked}"
        if report:
            told += f"\n\n{report_instruction(report)}"
        return told, f"{self.title} : {asked}"


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


def _skill_paths(skill: str) -> tuple[str, str]:
    """Where a skill may be, in the project settings.

    Returns:
        As a skill (`.claude/skills/<skill>/SKILL.md`), then as a command.
    """
    return f".claude/skills/{skill}/SKILL.md", f".claude/commands/{skill}.md"


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _parse(text: str | None, skill_exists: Callable[[str], bool]) -> Declared:
    if text is None:
        return Declared()
    try:
        content = safe_load(text)
    except YAMLError as error:
        return Declared(error=f"deckz.yml n'est pas du YAML valide :\n{error}")
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
            if not skill_exists(workflow.skill)
        },
    )


def declared(workspace: Path) -> Declared:
    """The workflows the workspace's `deckz.yml` declares.

    Returns:
        Them, or why the section is invalid.
    """
    path = workspace / "deckz.yml"
    try:
        text = path.read_text(encoding="utf8") if path.is_file() else None
    except (OSError, UnicodeDecodeError) as error:
        return Declared(error=str(error))
    return _parse(
        text,
        lambda skill: any((workspace / p).is_file() for p in _skill_paths(skill)),
    )


def declared_at(repository: Path, revision: str = "HEAD") -> Declared:
    """The workflows `deckz.yml` declares in a commit of `repository`.

    What a new workspace starting from it will offer, whatever the files of
    the checkout are.

    Returns:
        Them, or why the section is invalid.
    """
    shown = _git(repository, "show", f"{revision}:deckz.yml")
    return _parse(
        shown.stdout if shown.returncode == 0 else None,
        lambda skill: any(
            _git(repository, "cat-file", "-e", f"{revision}:{p}").returncode == 0
            for p in _skill_paths(skill)
        ),
    )


def decks_at(repository: Path, revision: str = "HEAD") -> list[str]:
    """The decks of a commit of `repository`.

    Returns:
        Each deck directory (one holding a `deck.yml`), sorted, as \
        `workspaces.decks` finds them in a checkout.
    """
    listed = _git(repository, "ls-tree", "-r", "--name-only", revision).stdout
    return sorted(
        path.removesuffix("/deck.yml")
        for path in listed.splitlines()
        if path.endswith("/deck.yml")
        and not any(part.startswith(".") for part in path.split("/"))
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


REPORTS_DIR = STATE_DIR / "rapports"
"""The workflows' reports, relative to the workspace: `<id>.md` and `<id>.json`."""


@dataclass(frozen=True)
class Item:
    """A finding of a report: a box to tick."""

    index: int
    line: int
    """Its line in the file, where its box is."""
    checked: bool
    text: str


@dataclass(frozen=True)
class Part:
    """A report's heading and the findings under it."""

    title: str
    notes: str
    items: list[Item]


@dataclass(frozen=True)
class Report:
    """A workflow's report in a workspace."""

    id: str
    workflow: str
    """The workflow's key."""
    deck: str
    started: str
    path: Path
    """The checklist, which the agent writes."""

    @property
    def relative(self) -> str:
        return (REPORTS_DIR / self.path.name).as_posix()

    def parts(self) -> list[Part]:
        return checklist(self.path.read_text(encoding="utf8"))

    def chosen(self) -> list[Item]:
        return [item for part in self.parts() for item in part.items if item.checked]


def report_id(workflow: Workflow, deck: str) -> str:
    """The report's name: one per workflow and deck, the last run's.

    Returns:
        The workflow's key, then the deck's path if any.
    """
    name = workflow.key + (f"--{deck}" if deck else "")
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name)


def start_report(workspace: Path, workflow: Workflow, deck: str) -> str:
    """Prepare the report of a workflow starting: the previous one goes.

    Returns:
        Its path, relative to the workspace, for the agent.
    """
    directory = workspace / REPORTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = report_id(workflow, deck)
    (directory / f"{name}.md").unlink(missing_ok=True)
    (directory / f"{name}.json").write_text(
        json.dumps(
            {
                "workflow": workflow.key,
                "deck": deck,
                "started": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf8",
    )
    return (REPORTS_DIR / f"{name}.md").as_posix()


def reports(workspace: Path) -> list[Report]:
    """The workspace's reports, written or still awaited.

    Returns:
        Them, the latest first.
    """
    found = []
    for meta in (workspace / REPORTS_DIR).glob("*.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        found.append(
            Report(
                meta.stem,
                str(data.get("workflow", "")),
                str(data.get("deck", "")),
                str(data.get("started", "")),
                meta.with_suffix(".md"),
            )
        )
    return sorted(found, key=lambda report: report.started, reverse=True)


def report(workspace: Path, report_name: str) -> Report | None:
    return next((r for r in reports(workspace) if r.id == report_name), None)


_BOX = re.compile(r"^(?P<indent>\s*)[-*+] \[(?P<mark>[ xX])\] ?(?P<text>.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.*?)\s*#*\s*$")


def checklist(text: str) -> list[Part]:
    """A report's findings: Markdown task lists, under their headings.

    A line indented under a box continues its finding; other lines are the
    heading's notes.

    Returns:
        The parts, in order; the first one untitled if the report starts
        without a heading.
    """
    parts: list[Part] = [Part("", "", [])]
    notes: list[list[str]] = [[]]
    count = 0
    current: list[str] | None = None
    current_indent = 0
    for number, line in enumerate(text.splitlines()):
        if heading := _HEADING.match(line):
            parts.append(Part(heading["title"], "", []))
            notes.append([])
            current = None
        elif box := _BOX.match(line):
            current = [box["text"]]
            current_indent = len(box["indent"])
            parts[-1].items.append(Item(count, number, box["mark"] != " ", box["text"]))
            count += 1
        elif (
            current is not None
            and line.strip()
            and (len(line) - len(line.lstrip()) > current_indent)
        ):
            current.append(line.strip())
            parts[-1].items[-1] = _with_text(parts[-1].items[-1], current)
        else:
            current = None
            if line.strip():
                notes[-1].append(line)
    found = [
        Part(part.title, "\n".join(lines), part.items)
        for part, lines in zip(parts, notes, strict=True)
    ]
    return [part for part in found if part.title or part.items or part.notes]


def _with_text(item: Item, lines: list[str]) -> Item:
    return Item(item.index, item.line, item.checked, "\n".join(lines))


def tick(path: Path, chosen: set[int]) -> None:
    """Tick exactly the findings `chosen` (by index) in the report's file."""
    text = path.read_text(encoding="utf8")
    lines = text.splitlines(keepends=True)
    for part in checklist(text):
        for item in part.items:
            mark = "x" if item.index in chosen else " "
            lines[item.line] = re.sub(
                r"\[[ xX]\]", f"[{mark}]", lines[item.line], count=1
            )
    path.write_text("".join(lines), encoding="utf8")
