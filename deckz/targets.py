from collections import OrderedDict
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from yaml import safe_load as yaml_safe_load

from deckz.exceptions import DeckzException
from deckz.paths import Paths


_logger = getLogger(__name__)


class Section:
    def __init__(self, title: Optional[str]):
        self.title = title
        self.inputs: List[Tuple[str, Optional[str]]] = []

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"title={repr(self.title)},"
            f"inputs={repr(self.inputs)})"
        )


class Dependencies:
    def __init__(self) -> None:
        self.local: Set[Path] = set()
        self.shared: Set[Path] = set()
        self.missing: Set[Path] = set()
        self.unused: Set[Path] = set()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"local={repr(self.local)},"
            f"shared={repr(self.shared)},"
            f"missing={repr(self.missing)},"
            f"unused={repr(self.unused)})"
        )

    @staticmethod
    def merge(*dependencies_list: "Dependencies") -> "Dependencies":
        dependencies = Dependencies()
        for ds in dependencies_list:
            dependencies.local |= ds.local
            dependencies.shared |= ds.shared
            dependencies.missing |= ds.missing
            dependencies.unused |= ds.unused - dependencies.local
        return dependencies

    def merge_dicts(
        *dependencies_dicts: Dict[str, "Dependencies"]
    ) -> Dict[str, "Dependencies"]:
        keys = set.union(*(set(d) for d in dependencies_dicts))
        merged_dict = {}
        for key in keys:
            merged_dict[key] = Dependencies.merge(
                *(d[key] for d in dependencies_dicts if key in d)
            )
        return merged_dict


class Target:
    def __init__(self, data: Dict[str, Any], paths: Paths):
        self.name = data["name"]
        local_latex_dir = paths.working_dir / self.name
        self.title = data["title"]
        self.dependencies = Dependencies()
        self.dependencies.unused |= set(local_latex_dir.glob("**/*.tex"))
        self.sections = []
        for section_config in data["sections"]:
            if not isinstance(section_config, dict):
                section_config = dict(path=section_config)
            section_path = section_config["path"]
            local_dir = local_latex_dir / section_path
            local_file = local_latex_dir / f"{section_path}.tex"
            shared_dir = paths.shared_latex_dir / section_path
            shared_file = paths.shared_latex_dir / f"{section_path}.tex"
            if local_dir.exists() and local_dir.resolve().is_dir():
                section, dependencies = self._parse_section_dir(
                    local_dir, local_latex_dir, section_config
                )
                self.dependencies.local |= dependencies
            elif local_file.exists() and local_file.resolve().is_file():
                section, dependencies = self._parse_section_file(
                    local_file, local_latex_dir, section_config
                )
                self.dependencies.local |= dependencies
            elif shared_dir.exists() and shared_dir.resolve().is_dir():
                section, dependencies = self._parse_section_dir(
                    shared_dir, paths.shared_latex_dir, section_config
                )
                self.dependencies.shared |= dependencies
            elif shared_file.exists() and shared_file.resolve().is_file():
                section, dependencies = self._parse_section_file(
                    shared_file, paths.shared_latex_dir, section_config
                )
                self.dependencies.shared |= dependencies
            else:
                self.dependencies.missing.add(section_path)
            self.sections.append(section)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={repr(self.name)},"
            f"title={repr(self.title)},"
            f"dependencies={repr(self.dependencies)},"
            f"sections={repr(self.sections)})"
        )

    def _parse_section_dir(
        self, section_dir: Path, latex_dir: Path, config: Dict[str, Any]
    ) -> Tuple[Section, Set[Path]]:
        with open(section_dir / "section.yml", encoding="utf8") as fh:
            default_config = yaml_safe_load(fh)
        title = config["title"] if "title" in config else default_config["title"]
        section = Section(title)
        dependencies = set()
        for include in default_config["includes"]:
            if not isinstance(include, dict):
                include = dict(path=include)
            if "excludes" in config and include["path"] in config["excludes"]:
                continue
            title, path = include.get("title"), include["path"]
            section.inputs.append(
                (f"{section_dir.relative_to(latex_dir)}/{path}", title)
            )
            dependencies.add((section_dir / path).with_suffix(".tex").resolve())
        return section, dependencies

    def _parse_section_file(
        self, section_file: Path, latex_dir: Path, config: Dict[str, Any]
    ) -> Tuple[Section, Set[Path]]:
        config_file = section_file.with_suffix(".yml")
        if "title" in config:
            title = config["title"]
        elif config_file.exists():
            with config_file.open(encoding="utf8") as fh:
                default_config = yaml_safe_load(fh)
            title = default_config["title"]
        else:
            title = None
        dependencies = set()
        section = Section(title)
        section.inputs.append(
            (f"{section_file.relative_to(latex_dir).with_suffix('')}", None)
        )
        dependencies.add(section_file.resolve())
        return section, dependencies


class Targets(Iterable[Target]):
    def __init__(
        self, paths: Paths, debug: bool, fail_on_missing: bool, whitelist: List[str]
    ) -> None:
        self._paths = paths
        path = paths.targets_debug if debug else paths.targets
        if not path.exists():
            if fail_on_missing:
                raise DeckzException(f"Could not find {path}.")
            else:
                self.targets = []
        with path.open("r", encoding="utf8") as fh:
            targets = [
                Target(data=target, paths=paths) for target in yaml_safe_load(fh)
            ]
        missing_dependencies = {
            target.name: target.dependencies.missing
            for target in targets
            if target.dependencies.missing
        }
        if missing_dependencies:
            raise DeckzException(
                "Could not find the following dependencies:\n%s"
                % "\n".join(
                    "  - %s:\n%s" % (k, "\n".join(f"    - {p}" for p in v))
                    for k, v in missing_dependencies.items()
                ),
            )
        target_names = set(target.name for target in targets)
        whiteset = set(whitelist)
        unmatched = whiteset - target_names
        if unmatched:
            raise DeckzException(
                "Could not find the following targets:\n%s"
                % "\n".join("  - %s" % name for name in unmatched)
            )
        self.targets = [
            target for target in targets if not whiteset or target.name in whiteset
        ]

    def get_dependencies(self) -> Dict[str, Dependencies]:
        return OrderedDict((t.name, t.dependencies) for t in self.targets)

    def __iter__(self) -> Iterator[Target]:
        return iter(self.targets)

    def __len__(self) -> int:
        return len(self.targets)
