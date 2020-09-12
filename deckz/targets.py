from collections import OrderedDict
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from yaml import safe_load as yaml_safe_load

from deckz.exceptions import DeckzException
from deckz.paths import Paths


_logger = getLogger(__name__)


SECTION_YML_VERSION = 3


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
        self.used: Set[Path] = set()
        self.missing: Set[str] = set()
        self.unused: Set[Path] = set()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"used={repr(self.used)},"
            f"missing={repr(self.missing)},"
            f"unused={repr(self.unused)})"
        )

    @staticmethod
    def merge(*dependencies_list: "Dependencies") -> "Dependencies":
        dependencies = Dependencies()
        for ds in dependencies_list:
            dependencies.used |= ds.used
            dependencies.missing |= ds.missing
            dependencies.unused |= ds.unused - dependencies.used
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
        self._paths = paths
        self.name = data["name"]
        local_latex_dir = paths.working_dir / self.name
        self.title = data["title"]
        self.dependencies = Dependencies()
        self.dependencies.unused.update(local_latex_dir.glob("**/*.tex"))
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
            elif local_file.exists() and local_file.resolve().is_file():
                section, dependencies = self._parse_section_file(
                    local_file, local_latex_dir, section_config
                )
            elif shared_dir.exists() and shared_dir.resolve().is_dir():
                section, dependencies = self._parse_section_dir(
                    shared_dir, paths.shared_latex_dir, section_config
                )
            elif shared_file.exists() and shared_file.resolve().is_file():
                section, dependencies = self._parse_section_file(
                    shared_file, paths.shared_latex_dir, section_config
                )
            else:
                dependencies = Dependencies()
                dependencies.missing.add(section_path)
            self.dependencies = Dependencies.merge(self.dependencies, dependencies)
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
        self, section_dir: Path, latex_dir: Path, custom_config: Dict[str, Any]
    ) -> Tuple[Section, Dependencies]:
        section_config_path = section_dir / f"{section_dir.name}.yml"
        with open(section_config_path, encoding="utf8") as fh:
            section_config = yaml_safe_load(fh)
        title = (
            custom_config["title"]
            if "title" in custom_config
            else section_config["title"]
        )
        if "flavor" not in custom_config:
            raise DeckzException(
                f"Mandatory flavor not specified in {section_dir.name} configuration "
                "of targets.yml."
            )
        flavor_name = custom_config["flavor"]
        if "flavors" not in section_config:
            raise DeckzException(
                f"Mandatory dictionary `flavors` not found in {section_config_path}."
            )
        flavors = section_config["flavors"]
        if flavor_name not in flavors:
            flavors_string = ", ".join("'%s'" % f for f in flavors)
            raise DeckzException(
                f"'{flavor_name}' not amongst available flavors: {flavors_string} "
                f"of {section_config_path}."
            )
        flavor = flavors[flavor_name]
        section = Section(title)
        dependencies = Dependencies()
        default_titles = section_config.get("default_titles")
        for item in flavor:
            if isinstance(item, str):
                filename = item
                if default_titles is not None:
                    title = default_titles.get(filename)
                else:
                    title = None
            else:
                filename, title = next(iter(item.items()))
            if "excludes" in custom_config and filename in custom_config["excludes"]:
                continue
            local_path = (section_dir / filename).with_suffix(".tex")
            shared_path = (self._paths.shared_latex_dir / filename).with_suffix(".tex")
            if local_path.exists():
                section.inputs.append(
                    (f"{section_dir.relative_to(latex_dir)}/{filename}", title)
                )
                dependencies.used.add(local_path.resolve())
            elif shared_path.exists():
                section.inputs.append((filename, title))
                dependencies.used.add(shared_path.resolve())
            else:
                dependencies.missing.add(filename)
        return section, dependencies

    def _parse_section_file(
        self, section_file: Path, latex_dir: Path, config: Dict[str, Any]
    ) -> Tuple[Section, Dependencies]:
        config_file = section_file.with_suffix(".yml")
        if "title" in config:
            title = config["title"]
        elif config_file.exists():
            with config_file.open(encoding="utf8") as fh:
                default_config = yaml_safe_load(fh)
            title = default_config["title"]
        else:
            title = None
        section = Section(title)
        section.inputs.append(
            (f"{section_file.relative_to(latex_dir).with_suffix('')}", None)
        )
        dependencies = Dependencies()
        dependencies.used.add(section_file.resolve())
        return section, dependencies


class Targets(Iterable[Target]):
    def __init__(
        self, paths: Paths, fail_on_missing: bool, whitelist: List[str]
    ) -> None:
        self._paths = paths
        if not paths.targets.exists():
            if fail_on_missing:
                raise DeckzException(f"Could not find {paths.targets}.")
            else:
                self.targets = []
        with paths.targets.open("r", encoding="utf8") as fh:
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
