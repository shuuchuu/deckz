from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from attr import attrib, Attribute, attrs, Factory
from yaml import safe_load as yaml_safe_load

from deckz.exceptions import DeckzException
from deckz.paths import Paths


_logger = getLogger(__name__)


SECTION_YML_VERSION = 3


@attrs(auto_attribs=True)
class SectionInput:
    path: str = attrib(converter=str)
    title: Optional[str]


@attrs(auto_attribs=True)
class Section:
    title: str
    inputs: List[SectionInput] = Factory(list)


@attrs(auto_attribs=True)
class Dependencies:
    used: Set[Path] = Factory(set)
    missing: Set[str] = Factory(set)
    unused: Set[Path] = Factory(set)

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


@attrs(auto_attribs=True)
class Target:
    name: str
    title: Optional[str]
    dependencies: Dependencies
    sections: List[Section]
    section_dependencies: Dict[str, Dependencies]
    section_flavors: DefaultDict[str, Set[str]]


@attrs(auto_attribs=True)
class TargetBuilder:
    _data: Dict[str, Any]
    _paths: Paths
    _local_latex_dir: Path = attrib(init=False)

    def __attrs_post_init__(self) -> None:
        self._local_dir = self._paths.current_dir / self._data["name"]
        self._local_latex_dir = self._local_dir / "latex"

    def build(self) -> Target:
        all_dependencies = Dependencies()
        all_dependencies.unused.update(self._local_latex_dir.glob("**/*.tex"))
        sections = []
        section_dependencies = {}
        section_flavors = defaultdict(set)
        for section_config in self._data["sections"]:
            if not isinstance(section_config, dict):
                section_config = dict(path=section_config)
            section_path = section_config["path"]
            section_flavors[section_path].add(section_config.get("flavor"))
            result = self._parse_section_dir(section_path, section_config)
            if result is None:
                result = self._parse_section_file(section_path, section_config)
            if result is not None:
                section, dependencies = result
                sections.append(section)
            else:
                dependencies = Dependencies()
                dependencies.missing.add(section_path)
            all_dependencies = Dependencies.merge(all_dependencies, dependencies)
            section_dependencies[section_path] = dependencies
        return Target(
            name=self._data["name"],
            title=self._data["title"],
            dependencies=all_dependencies,
            sections=sections,
            section_dependencies=section_dependencies,
            section_flavors=section_flavors,
        )

    def _parse_section_dir(
        self, section_path: str, custom_config: Dict[str, Any],
    ) -> Optional[Tuple[Section, Dependencies]]:
        local_section_dir = self._local_latex_dir / section_path
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
        section_config = yaml_safe_load(section_config_path.read_text(encoding="utf8"))
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
            self._process_item(
                item,
                section,
                dependencies,
                default_titles,
                custom_config,
                local_section_dir,
                shared_section_dir,
            )
        return section, dependencies

    def _process_item(
        self,
        item: Union[str, Dict[str, str]],
        section: Section,
        dependencies: Dependencies,
        default_titles: Optional[Dict[str, str]],
        section_config: Dict[str, Any],
        local_section_dir: Path,
        shared_section_dir: Path,
    ) -> None:
        if isinstance(item, str):
            filename = item
            if default_titles is not None:
                title = default_titles.get(filename)
            else:
                title = None
        else:
            filename, title = next(iter(item.items()))
        if "excludes" in section_config and filename in section_config["excludes"]:
            return
        if filename.startswith("/"):
            local_path = (self._local_latex_dir / filename[1:]).with_suffix(".tex")
            shared_path = (self._paths.shared_latex_dir / filename[1:]).with_suffix(
                ".tex"
            )
        else:
            local_path = (local_section_dir / filename).with_suffix(".tex")
            shared_path = (shared_section_dir / filename).with_suffix(".tex")
        local_relative_path = local_path.relative_to(self._local_dir)
        shared_relative_path = shared_path.relative_to(self._paths.shared_dir)
        if local_path.exists():
            section.inputs.append(
                SectionInput(local_relative_path.with_suffix(""), title)
            )
            dependencies.used.add(local_path.resolve())
        elif shared_path.exists():
            section.inputs.append(
                SectionInput(shared_relative_path.with_suffix(""), title)
            )
            dependencies.used.add(shared_path.resolve())
        else:
            dependencies.missing.add(filename)

    def _parse_section_file(
        self, section_path: str, config: Dict[str, Any]
    ) -> Optional[Tuple[Section, Dependencies]]:
        local_section_file = (self._local_latex_dir / section_path).with_suffix(".tex")
        shared_section_file = (self._paths.shared_latex_dir / section_path).with_suffix(
            ".tex"
        )
        if local_section_file.exists():
            section_file = local_section_file
            relative_path = section_file.relative_to(self._local_dir)
        elif shared_section_file.exists():
            section_file = shared_section_file
            relative_path = section_file.relative_to(self._paths.shared_dir)
        else:
            return None
        config_file = section_file.with_suffix(".yml")
        if "title" in config:
            title = config["title"]
        elif config_file.exists():
            title = yaml_safe_load(config_file.read_text(encoding="utf8"))["title"]
        else:
            title = None
        section = Section(title)
        section.inputs.append(SectionInput(path=relative_path, title=None))
        dependencies = Dependencies()
        dependencies.used.add(section_file.resolve())
        return section, dependencies


@attrs(auto_attribs=True)
class Targets(Iterable[Target]):
    _targets: List[Target] = attrib()
    _paths: Paths

    @classmethod
    def from_file(
        cls, paths: Paths, whitelist: Optional[List[str]] = None
    ) -> "Targets":
        if not paths.targets.exists():
            raise DeckzException(f"Could not find {paths.targets}.")
        content = yaml_safe_load(paths.targets.read_text(encoding="utf8"))
        targets = [
            TargetBuilder(data=target, paths=paths).build() for target in content
        ]
        if whitelist is not None:
            cls._filter_targets(targets, frozenset(whitelist), paths)
        return Targets(targets, paths)

    @_targets.validator
    def _check_targets(self, attribute: Attribute, value: List[Target]) -> None:
        missing_dependencies = {
            target.name: target.dependencies.missing
            for target in value
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

    @staticmethod
    def _filter_targets(
        targets: Iterable[Target], whiteset: FrozenSet[str], paths: Paths
    ) -> List[Target]:
        unmatched = whiteset - frozenset(target.name for target in targets)
        if unmatched:
            raise DeckzException(
                f"Incorrect targets {paths.targets}. "
                "Could not find the following targets:\n%s"
                % "\n".join("  - %s" % name for name in unmatched)
            )
        return [target for target in targets if target.name in whiteset]

    def __iter__(self) -> Iterator[Target]:
        return iter(self._targets)

    def __len__(self) -> int:
        return len(self._targets)
