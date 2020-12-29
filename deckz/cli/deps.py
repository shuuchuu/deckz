from collections import defaultdict
from itertools import chain
from pathlib import Path
from typing import DefaultDict, Dict, FrozenSet, Iterable, Mapping, Optional, Set, Tuple

from git import Repo
from git.exc import InvalidGitRepositoryError
from rich.console import Console
from rich.padding import Padding
from rich.progress import Progress, track
from rich.table import Table
from yaml import safe_load as yaml_safe_load

from deckz.cli import app
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths, Paths
from deckz.targets import Targets
from deckz.utils import get_section_config_paths


@app.command()
def deps(
    unused: bool = True,
    git: bool = True,
    section: Optional[str] = None,
    flavor: Optional[str] = None,
    path: str = ".",
) -> None:
    """Give information about shared modules usage."""
    paths = GlobalPaths(path)
    with Progress() as progress:
        targets_progress = progress.add_task("Retrieving targets files", start=False)
        sections_progress = progress.add_task("Retrieving section files", start=False)

        targets_paths = list(paths.git_dir.glob("**/targets.yml"))
        progress.update(
            targets_progress, total=len(targets_paths), completed=len(targets_paths)
        )
        progress.start_task(targets_progress)

        section_paths = get_section_config_paths(paths.shared_latex_dir)
        progress.update(
            sections_progress, total=len(section_paths), completed=len(section_paths)
        )
        progress.start_task(sections_progress)

    all_targets_dependencies: Dict[str, Dict[str, Set[str]]] = defaultdict(dict)
    by_sections: DefaultDict[str, DefaultDict[str, Set[Tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for targets_path in track(targets_paths, description="Processing targets files"):
        _process_targets(targets_path, all_targets_dependencies, by_sections)

    touched = _get_touched_files(paths)

    if git:
        _print_changed_report(touched, all_targets_dependencies)
    if unused:
        _print_unused_report(section_paths, by_sections)
    if section is not None:
        _print_section_report(section, flavor, by_sections)


def _compute_shared_dependencies(
    dependencies: Set[Path], paths: GlobalPaths
) -> Set[str]:
    shared_dependencies = set()
    for dependency in dependencies:
        try:
            relative_dependency = dependency.relative_to(paths.shared_latex_dir)
            shared_dependencies.add(str(relative_dependency))
        except ValueError:
            pass
    return shared_dependencies


def _process_targets(
    targets_path: Path,
    all_targets_dependencies: Dict[str, Dict[str, Set[str]]],
    by_sections: Mapping[str, Mapping[str, Set[Tuple[str, str]]]],
) -> None:
    paths = Paths(str(targets_path.parent))
    targets_name = str(paths.current_dir.relative_to(paths.git_dir))
    targets = Targets.from_file(paths)
    for target in targets:
        for section_path, dependencies in target.section_dependencies.items():
            section_flavors = target.section_flavors[section_path]
            shared = False
            for dependency_path in dependencies.used:
                if _relative_to_shared_latex(paths, str(dependency_path)) is not None:
                    shared = True
                    break
            if shared:
                for section_flavor in section_flavors:
                    by_sections[section_path][section_flavor].add(
                        (targets_name, target.name)
                    )
        shared_dependencies = _compute_shared_dependencies(
            target.dependencies.used, paths
        )
        all_targets_dependencies[targets_name][target.name] = shared_dependencies


def _get_touched_files(paths: GlobalPaths) -> FrozenSet[str]:
    try:
        repository = Repo(str(paths.git_dir))
        index = repository.index
        staged_diffs = index.diff("HEAD")
        unstaged_diffs = index.diff(None)
        untracked_files = repository.untracked_files
        touched = set()
        for diff in chain(staged_diffs, unstaged_diffs):
            for p in [diff.a_path, diff.b_path]:
                relative_to_shared_latex = _relative_to_shared_latex(paths, p)
                if relative_to_shared_latex is not None:
                    touched.add(relative_to_shared_latex)
        for untracked_file in untracked_files:
            relative_to_shared_latex = _relative_to_shared_latex(paths, untracked_file)
            if relative_to_shared_latex is not None:
                touched.add(relative_to_shared_latex)
        return frozenset(touched)
    except InvalidGitRepositoryError as e:
        raise DeckzException(
            "Could not find the path of the current git working directory. "
            "Are you in one?"
        ) from e


def _print_changed_report(
    touched: FrozenSet[str], all_targets_dependencies: Dict[str, Dict[str, Set[str]]]
) -> None:
    console = Console()
    console.print()
    console.print()
    console.rule("[bold]Decks affected by uncommited changes", align="left")
    console.print()
    table = Table("Deck", "Targets")
    for targets_name, targets_dependencies in all_targets_dependencies.items():
        touched_targets = []
        for target_name, target_dependencies in targets_dependencies.items():
            if touched.intersection(target_dependencies):
                touched_targets.append(target_name)
        if touched_targets:
            table.add_row(targets_name, " ".join(touched_targets))
    console.print(Padding(table if table.row_count else "None.", (0, 0, 0, 2)))


def _print_unused_report(
    section_paths: Iterable[Path],
    by_sections: Mapping[str, Mapping[str, Set[Tuple[str, str]]]],
) -> None:
    console = Console()
    console.print()
    console.print()
    console.rule("[bold]Unused flavors", align="left")
    console.print()
    table = Table("Section", "Flavors")
    flavors = defaultdict(set)
    for section_path in section_paths:
        with section_path.open(encoding="utf8") as fh:
            section_config = yaml_safe_load(fh)
        flavors[section_path.parent.name].update(section_config["flavors"])
    for section_name, section_flavors in sorted(flavors.items()):
        unused_flavors = [
            flavor
            for flavor in section_flavors
            if not by_sections[section_name][flavor]
        ]
        if unused_flavors:
            table.add_row(section_name, " ".join(sorted(unused_flavors)))
    console.print(Padding(table if table.row_count else "None.", (0, 0, 0, 2)))


def _print_section_report(
    section: str,
    flavor: Optional[str],
    by_sections: Mapping[str, Mapping[str, Set[Tuple[str, str]]]],
) -> None:
    console = Console()
    console.print()
    console.print()
    title = section
    if flavor is not None:
        title += f" {flavor}"
    console.rule(f"[bold]Decks depending on [italic]{title}", align="left")
    console.print()
    table = Table("Deck", "Targets")
    if flavor is None:
        flavors_dependencies = by_sections[section]
        for deck_path, target_name in sorted(set.union(*flavors_dependencies.values())):
            table.add_row(deck_path, target_name)
    else:
        flavors_dependencies = by_sections[section]
        for deck_path, target_name in sorted(flavors_dependencies[flavor]):
            table.add_row(deck_path, target_name)
    console.print(Padding(table if table.row_count else "None.", (0, 0, 0, 2)))


def _relative_to_shared_latex(paths: GlobalPaths, file_path: str) -> Optional[str]:
    try:
        return str((paths.git_dir / file_path).relative_to(paths.shared_latex_dir))
    except ValueError:
        return None
