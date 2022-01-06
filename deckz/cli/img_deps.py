from pathlib import Path
from re import compile as re_compile
from typing import Dict, Iterator, Optional

from rich.console import Console
from rich.table import Table
from typer import Argument, Option
from yaml import safe_load

from deckz.cli import app
from deckz.paths import GlobalPaths
from deckz.targets import Dependencies, Targets


@app.command()
def img_deps(
    image: Optional[str] = Argument(
        None, help="Specific image to track, like img/turing or tikz/variables"
    ),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Find which latex files use an image."""
    global_paths = GlobalPaths.from_defaults(workdir)
    if image is None:
        check_images(global_paths)
    else:
        track_specific_image(image, global_paths)


def check_images(global_paths: GlobalPaths) -> None:
    console = Console(highlight=False)
    with console.status("Computing full section dependencies"):
        section_dependencies: Dict[str, Dependencies] = {}
        for paths in global_paths.decks_paths():
            targets = Targets.from_file(paths)
            for target in targets:
                section_dependencies = Dependencies.merge_dicts(
                    section_dependencies, target.section_dependencies
                )
    with console.status("Computing images used by section"):
        images = {}
        for section, dependencies in section_dependencies.items():
            images[section] = set(_section_images(section, dependencies, global_paths))
    table = Table("Section", "Unlicensed images")
    for section in sorted(section_dependencies, key=lambda s: len(images[s])):
        section_images = images[section]
        if section_images:
            table.add_row(section, f"{len(section_images)}")
    if table.row_count:
        console.print(table)


def track_specific_image(image: str, global_paths: GlobalPaths) -> None:
    console = Console(highlight=False)
    pattern = re_compile(fr'(\\V{{\[?"{image}".*\]? \| image}})')
    current_dir = global_paths.current_dir
    for latex_dir in global_paths.latex_dirs():
        for f in latex_dir.rglob("*.tex"):
            if pattern.search(f.read_text(encoding="utf8")):
                console.print(f"[link=file://{f}]{f.relative_to(current_dir)}[/link]")


_pattern = re_compile(r'\\V{\[?"(.+?)".*\]? \| image}')


def _section_images(
    section: str, dependencies: Dependencies, global_paths: GlobalPaths
) -> Iterator[str]:
    for latex_file in dependencies.used:
        for match in _pattern.finditer(latex_file.read_text(encoding="utf8")):
            if match is None:
                continue
            image = match.group(1)
            if not _image_license(image, global_paths):
                yield image


def _image_license(image: str, global_paths: GlobalPaths) -> Optional[str]:
    metadata_path = (global_paths.shared_dir / image).with_suffix(".yml")
    if not metadata_path.exists():
        return None
    metadata = safe_load(metadata_path.read_text(encoding="utf8"))
    return metadata["license"]
