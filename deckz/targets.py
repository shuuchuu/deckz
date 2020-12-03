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
        self.local_latex_dir = paths.current_dir / self.name
        self.title = data["title"]
        self.dependencies = Dependencies()
        self.dependencies.unused.update(self.local_latex_dir.glob("**/*.tex"))
        self.sections = []
        self.section_dependencies = {}
        self.section_flavors = {}
        for section_config in data["sections"]:
            if not isinstance(section_config, dict):
                section_config = dict(path=section_config)
            section_path = section_config["path"]
            self.section_flavors[section_path] = section_config.get("flavor")
            result = self._parse_section_dir(section_path, section_config)
            found_section = False
            if result is not None:
                found_section = True
                section, dependencies = result
            else:
                result = self._parse_section_file(section_path, section_config)
                if result is not None:
                    found_section = True
                    section, dependencies = result
                else:
                    dependencies = Dependencies()
                    dependencies.missing.add(section_path)
            self.dependencies = Dependencies.merge(self.dependencies, dependencies)
            if found_section:
                self.sections.append(section)
            self.section_dependencies[section_path] = dependencies

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={repr(self.name)},"
            f"title={repr(self.title)},"
            f"dependencies={repr(self.dependencies)},"
            f"sections={repr(self.sections)})"
        )

    def _parse_section_dir(
        self, section_path: str, custom_config: Dict[str, Any]
    ) -> Optional[Tuple[Section, Dependencies]]:
        local_section_dir = self.local_latex_dir / section_path
        local_section_config_path = (local_section_dir / section_path).with_suffix(
            ".yml"
        )
        shared_section_dir = self._paths.shared_latex_dir / section_path
        shared_section_config_path = (shared_section_dir / section_path).with_suffix(
            ".yml"
        )
        if local_section_config_path.exists():
            section_config_path = local_section_config_path
        elif shared_section_config_path.exists():
            section_config_path = shared_section_config_path
        else:
            return None
        with section_config_path.open(encoding="utf8") as fh:
            section_config = yaml_safe_load(fh)
        title = (
            custom_config["title"]
            if "title" in custom_config
            else section_config["title"]
        )
        if "flavor" not in custom_config:
            raise DeckzException(
                f"Incorrect targets {self._paths.targets}. "
                f"Mandatory flavor not specified in {section_path} configuration."
            )
        flavor_name = custom_config["flavor"]
        if "flavors" not in section_config:
            raise DeckzException(
                f"Incorrect targets {self._paths.targets}. "
                f"Mandatory dictionary `flavors` not found in {section_config_path}."
            )
        flavors = section_config["flavors"]
        if flavor_name not in flavors:
            flavors_string = ", ".join("'%s'" % f for f in flavors)
            raise DeckzException(
                f"Incorrect targets {self._paths.targets}. "
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
            if filename.startswith("/"):
                local_path = (self.local_latex_dir / filename[1:]).with_suffix(".tex")
                shared_path = (self._paths.shared_latex_dir / filename[1:]).with_suffix(
                    ".tex"
                )
            else:
                local_path = (local_section_dir / filename).with_suffix(".tex")
                shared_path = (shared_section_dir / filename).with_suffix(".tex")
            local_relative_path = local_path.relative_to(self.local_latex_dir)
            shared_relative_path = shared_path.relative_to(self._paths.shared_latex_dir)
            if local_path.exists():
                section.inputs.append((str(local_relative_path.with_suffix("")), title))
                dependencies.used.add(local_path.resolve())
            elif shared_path.exists():
                section.inputs.append(
                    (str(shared_relative_path.with_suffix("")), title)
                )
                dependencies.used.add(shared_path.resolve())
            else:
                dependencies.missing.add(filename)
        return section, dependencies

    def _parse_section_file(
        self, section_path: str, config: Dict[str, Any]
    ) -> Optional[Tuple[Section, Dependencies]]:
        local_section_file = (self.local_latex_dir / section_path).with_suffix(".tex")
        shared_section_file = (self._paths.shared_latex_dir / section_path).with_suffix(
            ".tex"
        )
        if local_section_file.exists():
            section_file = local_section_file
        elif shared_section_file.exists():
            section_file = shared_section_file
        else:
            return None
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
        section.inputs.append((section_path, None))
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
                f"Incorrect targets {self._paths.targets}. "
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
                f"Incorrect targets {self._paths.targets}. "
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

    def __repr__(self) -> str:
        return f"Targets(targets={repr(self.targets)}"
