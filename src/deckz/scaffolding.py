"""The mechanical half of new work: `deckz new deck|section`, `deckz labs new`.

Each creates the files a new deck, shared section or lab notebook pair needs,
in both languages, and refuses to overwrite anything. What goes in them (which
sections a program needs, what a lab teaches) stays with people. A repository
can give its own starting files under `templates/scaffold/` (see each
function); otherwise minimal ones are written.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .exceptions import ScaffoldRefusedError
from .models import LANGS

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

LAB_TYPES = ("hands-on", "demo")
_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _check_path(path: str, what: str) -> list[str]:
    parts = path.strip("/").split("/")
    if not all(_NAME.fullmatch(part) for part in parts):
        msg = (
            f"{what} {path!r}: each part must be lowercase ASCII words joined by "
            "dashes, e.g. nn/cnn/image-segmentation"
        )
        raise ScaffoldRefusedError(msg)
    return parts


def _title(name: str) -> str:
    return name.replace("-", " ").capitalize()


def _refuse_existing(paths: list[Path], git_dir: Path) -> None:
    if existing := [path for path in paths if path.exists()]:
        names = ", ".join(str(path.relative_to(git_dir)) for path in existing)
        msg = f"{names} already exists: pick another name, or edit it"
        raise ScaffoldRefusedError(msg)


@dataclass(frozen=True)
class NewLab:
    paths: tuple[Path, ...]
    ids: tuple[str, ...]


def _minimal_notebook(kind: str, title: str, solution_heading: str) -> dict[str, Any]:
    def cell(cell_type: str, source: str) -> dict[str, Any]:
        cell: dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": source,
        }
        if cell_type == "code":
            cell |= {"execution_count": None, "outputs": []}
        return cell

    cells = [cell("markdown", f"# {title}")]
    if kind == "hands-on":
        cells += [
            cell("markdown", "## Exercise 1"),
            cell("code", ""),
            cell("markdown", f"### {solution_heading}"),
            cell("code", ""),
        ]
    else:
        cells.append(cell("code", ""))
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def new_lab(settings: "GlobalSettings", lab: str, kind: str) -> NewLab:
    """Create a lab's notebook pair, `<lab>/<kind>-<lang>.ipynb`, with their IDs.

    Both languages start from the same notebook (same cells, same cell ids,
    as `lab-pairs` wants): `templates/scaffold/lab/<kind>.ipynb` if the
    repository has one, else a minimal one. The text is then the author's
    to write, and to translate.

    Args:
        settings: The repository's settings.
        lab: The lab's path under the notebooks directory, e.g. \
            `nn/cnn/image-segmentation-keras`.
        kind: `hands-on` or `demo`.

    Returns:
        The notebooks written, and the IDs they got.

    Raises:
        ScaffoldRefusedError: On a bad name or kind, or if a notebook exists.
    """
    from .labs.ids import assign_ids
    from .labs.notebook import canonical_dump, sync_collapsed_sections

    if kind not in LAB_TYPES:
        msg = f"a lab is {' or '.join(LAB_TYPES)}, not {kind!r}"
        raise ScaffoldRefusedError(msg)
    parts = _check_path(lab, "lab")
    paths = settings.paths
    lab_dir = paths.labs_notebooks_dir.joinpath(*parts)
    notebooks = [lab_dir / f"{kind}-{lang}.ipynb" for lang in LANGS]
    _refuse_existing(notebooks, paths.git_dir)
    template = paths.templates_dir / "scaffold" / "lab" / f"{kind}.ipynb"
    notebook = (
        json.loads(template.read_text(encoding="utf-8"))
        if template.is_file()
        else _minimal_notebook(kind, _title(parts[-1]), settings.labs.solution_heading)
    )
    sync_collapsed_sections(notebook, heading=settings.labs.solution_heading)
    lab_dir.mkdir(parents=True, exist_ok=True)
    text = canonical_dump(notebook)
    for path in notebooks:
        path.write_text(text, encoding="utf-8")
    assigned = assign_ids(
        paths.labs_notebooks_dir,
        paths.content_dir,
        id_metadata_key=settings.labs.id_metadata_key,
        id_pattern=settings.labs.id_pattern,
    )
    new = set(notebooks)
    return NewLab(
        tuple(notebooks), tuple(lab_id for lab_id, path in assigned if path in new)
    )


def new_section(
    settings: "GlobalSettings", section: str, title: str | None = None
) -> list[Path]:
    """Create a shared section: its `.yml` with a `full` flavor, and a first file.

    `content/<section>/<name>.yml`, `<name>.md` and `en/<name>.md`, `<name>`
    being the section's last path part. Both languages get the same title
    until someone translates it. A bad name, or an existing section, raises
    `ScaffoldRefusedError`.

    Returns:
        The files written.
    """
    import yaml

    parts = _check_path(section, "section")
    name = parts[-1]
    section_dir = settings.paths.content_dir.joinpath(*parts)
    yml = section_dir / f"{name}.yml"
    files = [yml, section_dir / f"{name}.md", section_dir / "en" / f"{name}.md"]
    _refuse_existing(files, settings.paths.git_dir)
    title = title or _title(name)
    definition = {
        "title": {"fr": title, "en": title},
        "flavors": [{"name": "full", "includes": [name]}],
    }
    (section_dir / "en").mkdir(parents=True, exist_ok=True)
    yml.write_text(
        yaml.safe_dump(definition, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for path in files[1:]:
        path.write_text(f"# {title}\n", encoding="utf-8")
    return files


def new_deck(
    settings: "GlobalSettings", directory: Path, name: str, title: str
) -> list[Path]:
    """Create a deck in `directory`: from `templates/scaffold/deck/`, or a bare one.

    The repository's template directory is copied file by file, each file
    rendered with Jinja (`{{ name }}`, `{{ title }}`) on the way, and a
    `.jinja` suffix dropped from its name: the template's `deck.yml.jinja`
    keeps deckz (and YAML tools) from taking the template for a deck.
    Without one, only a `deck.yml` with a single empty part is written.

    Returns:
        The files written.

    Raises:
        ScaffoldRefusedError: If `directory` already holds a deck.
    """
    import yaml
    from jinja2 import Environment, StrictUndefined

    git_dir = settings.paths.git_dir
    directory = directory.resolve()
    if not directory.is_relative_to(git_dir):
        msg = f"{directory} isn't in the repository {git_dir}"
        raise ScaffoldRefusedError(msg)
    _refuse_existing([directory / "deck.yml"], git_dir)
    template_dir = settings.paths.templates_dir / "scaffold" / "deck"
    if not template_dir.is_dir():
        directory.mkdir(parents=True, exist_ok=True)
        deck_yml = directory / "deck.yml"
        part = {"name": "main", "title": title, "sections": []}
        deck_yml.write_text(
            yaml.safe_dump(
                {"name": name, "parts": [part]}, allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
        return [deck_yml]
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    targets = {
        source: directory
        / source.relative_to(template_dir).with_name(source.name.removesuffix(".jinja"))
        for source in sorted(template_dir.rglob("*"))
        if source.is_file()
    }
    _refuse_existing(list(targets.values()), git_dir)
    for source, target in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        text = env.from_string(source.read_text(encoding="utf-8")).render(
            name=name, title=title
        )
        target.write_text(text, encoding="utf-8")
    return list(targets.values())
