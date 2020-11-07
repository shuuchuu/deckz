from collections import defaultdict
from itertools import chain
from typing import Dict, Optional, Set

from click import Path as ClickPath, secho
from git import Repo
from git.exc import InvalidGitRepositoryError
from tqdm import tqdm

from deckz.cli import command, option
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths, Paths
from deckz.targets import Targets


@command
@option(
    "--path",
    type=ClickPath(exists=True, readable=True, file_okay=False),
    default=".",
    help="Path to run the command from.",
)
def deps(path: str) -> None:
    """Give information about shared modules usage."""
    paths = GlobalPaths(path)
    targets_paths = list(paths.git_dir.glob("**/targets.yml"))

    all_targets_dependencies: Dict[str, Dict[str, Set[str]]] = defaultdict(dict)
    for targets_path in tqdm(targets_paths, "Processing targets files"):
        paths = Paths(str(targets_path.parent))
        targets_name = str(paths.current_dir.relative_to(paths.git_dir))
        targets = Targets(paths, fail_on_missing=False, whitelist=[])
        for target in targets:
            shared_dependencies = set()
            for dependency_path in target.dependencies.used:
                try:
                    relative_dependency_path = dependency_path.relative_to(
                        paths.shared_latex_dir
                    )
                    shared_dependencies.add(str(relative_dependency_path))
                except ValueError:
                    pass
            all_targets_dependencies[targets_name][target.name] = shared_dependencies

    def _relative_to_shared_latex(file_path: str) -> Optional[str]:
        try:
            return str((paths.git_dir / file_path).relative_to(paths.shared_latex_dir))
        except ValueError:
            return None

    try:
        repository = Repo(str(path), search_parent_directories=True)
        index = repository.index
        staged_diffs = index.diff("HEAD")
        unstaged_diffs = index.diff(None)
        untracked_files = repository.untracked_files
        touched = set()
        for diff in chain(staged_diffs, unstaged_diffs):
            for p in [diff.a_path, diff.b_path]:
                relative_to_shared_latex = _relative_to_shared_latex(p)
                if relative_to_shared_latex is not None:
                    touched.add(relative_to_shared_latex)
        for untracked_file in untracked_files:
            relative_to_shared_latex = _relative_to_shared_latex(untracked_file)
            if relative_to_shared_latex is not None:
                touched.add(relative_to_shared_latex)
    except InvalidGitRepositoryError as e:
        raise DeckzException(
            "Could not find the path of the current git working directory. "
            "Are you in one?"
        ) from e

    for targets_name, targets_dependencies in all_targets_dependencies.items():
        touched_targets = []
        for target_name, target_dependencies in targets_dependencies.items():
            if touched.intersection(target_dependencies):
                touched_targets.append(target_name)
        if touched_targets:
            secho(targets_name, fg="green", nl=False)
            secho(f" {' '.join(touched_targets)}", fg="blue")
