from logging import getLogger
from pathlib import Path
from sys import exit
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Set

from yaml import safe_load as yaml_safe_load

from deckz.paths import paths


_logger = getLogger(__name__)


class Section(NamedTuple):
    title: str
    includes: List[str]

    @staticmethod
    def from_dict(input_dict: Dict[str, Any]) -> "Section":
        return Section(**input_dict)


class Dependencies:
    def __init__(self) -> None:
        self.local: Set[Path] = set()
        self.shared: Set[Path] = set()
        self.missing: Set[Path] = set()
        self.unused: Set[Path] = set()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"local={self.local},"
            f"shared={self.shared},"
            f"missing={self.missing},"
            f"unused={self.unused})"
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


class Target(NamedTuple):
    name: str
    title: str
    sections: List[Section]

    @staticmethod
    def from_dict(input_dict: Dict[str, Any]) -> "Target":
        return Target(
            name=input_dict["name"],
            title=input_dict["title"],
            sections=[Section.from_dict(section) for section in input_dict["sections"]],
        )

    def get_dependencies(self) -> Dependencies:
        dependencies_dir = Path(self.name)
        dependencies = Dependencies()
        dependencies.unused = set(d.resolve() for d in dependencies_dir.glob("*.tex"))
        for section in self.sections:
            for include in section.includes:
                local_path = (dependencies_dir / include).with_suffix(".tex").resolve()
                if local_path in dependencies.unused:
                    dependencies.unused.remove(local_path)
                shared_path = (paths.shared_latex_dir / include).with_suffix(".tex")
                if local_path.exists():
                    dependencies.local.add(local_path)
                elif shared_path.exists():
                    dependencies.shared.add(shared_path)
                else:
                    dependencies.missing.add(local_path)
        return dependencies


class Targets(Iterable[Target]):
    def __init__(
        self, debug: bool, fail_on_missing: bool, whitelist: List[str]
    ) -> None:
        path = paths.targets_debug if debug else paths.targets
        if not path.exists():
            if fail_on_missing:
                _logger.critical(f"Could not find {path}.")
                exit(1)
            else:
                self.targets = []
        with path.open("r", encoding="utf8") as fh:
            targets = [Target.from_dict(target) for target in yaml_safe_load(fh)]
        target_names = set(target.name for target in targets)
        whiteset = set(whitelist)
        unmatched = whiteset - target_names
        if unmatched:
            _logger.critical(
                "Could not find the following targets:\n%s",
                "\n".join("  - %s" % name for name in unmatched),
            )
            exit(1)
        self.targets = [
            target for target in targets if not whiteset or target.name in whiteset
        ]

    def get_dependencies(self) -> Dependencies:
        return Dependencies.merge(*(t.get_dependencies() for t in self.targets))

    def __iter__(self) -> Iterator[Target]:
        return iter(self.targets)

    def __len__(self) -> int:
        return len(self.targets)
