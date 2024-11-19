from collections import defaultdict
from collections.abc import Iterable, Iterator, Set
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError
from yaml import safe_load as safe_load

from ..configuring.paths import Paths
from ..exceptions import DeckzError

_logger = getLogger(__name__)


@dataclass(frozen=True)
class Title:
    title: str
    level: int


class DirSectionConfig(BaseModel):
    default_titles: dict[str, str] | None = None
    flavors: dict[str, list[str | dict[str, str | None]]]
    title: str

    @classmethod
    def from_yaml_file(cls, path: Path) -> "DirSectionConfig":
        try:
            return cls.model_validate(safe_load(path.read_text(encoding="utf8")))
        except (OSError, ValidationError) as e:
            msg = f"could not load {path} section config"
            raise DeckzError(msg) from e


Content = str
ContentOrTitle = Content | Title


@dataclass(frozen=True)
class PartSlides:
    title: str | None
    sections: list[ContentOrTitle] = field(default_factory=list)


@dataclass
class Dependencies:
    used: set[Path] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)
    unused: set[Path] = field(default_factory=set)

    def update(self, other: "Dependencies") -> None:
        self.used |= other.used
        self.missing |= other.missing
        self.unused |= other.unused - self.used
        self.unused -= other.used

    @staticmethod
    def merge(*dependencies_list: "Dependencies") -> "Dependencies":
        dependencies = Dependencies()
        for ds in dependencies_list:
            dependencies.used |= ds.used
            dependencies.missing |= ds.missing
            dependencies.unused |= ds.unused - dependencies.used
            dependencies.unused -= ds.used
        return dependencies

    @staticmethod
    def merge_dicts(
        *dependencies_dicts: dict[str, "Dependencies"],
    ) -> dict[str, "Dependencies"]:
        keys = set.union(*(set(d) for d in dependencies_dicts))
        merged_dict = {}
        for key in keys:
            merged_dict[key] = Dependencies.merge(
                *(d[key] for d in dependencies_dicts if key in d)
            )
        return merged_dict


@dataclass
class Target:
    name: str
    dependencies: Dependencies
    parts: list[PartSlides]
    section_dependencies: defaultdict[str, Dependencies]
    section_flavors: defaultdict[str, set[str]]

    @classmethod
    def from_targets(cls, targets: Iterable["Target"], name: str) -> "Target":
        dependencies = Dependencies.merge(*(t.dependencies for t in targets))
        parts = [p for t in targets for p in t.parts]
        section_dependencies: defaultdict[str, Dependencies] = defaultdict(Dependencies)
        for t in targets:
            for k, v in t.section_dependencies.items():
                section_dependencies[k].update(v)
        section_flavors = defaultdict(set)
        for target in targets:
            for key, value in target.section_flavors.items():
                section_flavors[key].update(value)
        return Target(name, dependencies, parts, section_dependencies, section_flavors)


@dataclass(frozen=True)
class TargetBuilder:
    data: dict[str, Any]
    paths: Paths

    def build(self) -> Target:
        all_dependencies = Dependencies()
        all_dependencies.unused.update(self.paths.local_latex_dir.glob("**/*.tex"))
        all_items = []
        section_dependencies: defaultdict[str, Dependencies] = defaultdict(Dependencies)
        section_flavors = defaultdict(set)
        for section_config in self.data["sections"]:
            if not isinstance(section_config, dict):
                section_config = {"path": section_config}
            section_path = section_config["path"]
            section_flavors[section_path].add(section_config.get("flavor"))
            result = self._parse_section_dir(
                section_path, section_config, 0, section_flavors, section_dependencies
            )
            if result is None:
                result = self._parse_section_file(section_path, section_config, 0)
            if result is not None:
                items, dependencies = result
                all_items.extend(items)
            else:
                dependencies = Dependencies()
                dependencies.missing.add(section_path)
            all_dependencies.update(dependencies)
            section_dependencies[section_path].update(dependencies)
        return Target(
            name=self.data["name"],
            dependencies=all_dependencies,
            parts=[PartSlides(title=self.data["title"], sections=all_items)],
            section_dependencies=section_dependencies,
            section_flavors=section_flavors,
        )

    def _parse_section_dir(
        self,
        section_path_str: str,
        custom_config: dict[str, Any],
        title_level: int,
        section_flavors: defaultdict[str, set[str]],
        section_dependencies: defaultdict[str, Dependencies],
    ) -> tuple[list[ContentOrTitle], Dependencies] | None:
        section_path = Path(section_path_str)
        local_section_dir = self.paths.local_latex_dir / section_path
        local_section_config_path = (local_section_dir / section_path).with_suffix(
            ".yml"
        )
        shared_section_dir = self.paths.shared_latex_dir / section_path
        shared_section_config_path = (
            shared_section_dir / section_path.parts[-1]
        ).with_suffix(".yml")
        dependencies = Dependencies()
        if local_section_config_path.exists():
            section_config_path = local_section_config_path
        elif shared_section_config_path.exists():
            section_config_path = shared_section_config_path
        else:
            return None
        section_config = DirSectionConfig.from_yaml_file(section_config_path)
        title = custom_config.get("title", section_config.title)
        if "flavor" not in custom_config:
            msg = (
                f"incorrect targets {self.paths.targets}. "
                f"Mandatory flavor not specified in {section_path} configuration"
            )
            raise DeckzError(msg)
        flavor_name = custom_config["flavor"]
        if flavor_name not in section_config.flavors:
            flavors_string = ", ".join(f"'{f}'" for f in section_config.flavors)
            msg = (
                f"incorrect targets {self.paths.targets}. "
                f"'{flavor_name}' not amongst available flavors: {flavors_string} "
                f"of {section_config_path}"
            )
            raise DeckzError(msg)

        flavor = section_config.flavors[flavor_name]
        items: list[ContentOrTitle] = [Title(title=title, level=title_level)]
        for item in flavor:
            self._process_item(
                item=item,
                items=items,
                dependencies=dependencies,
                default_titles=section_config.default_titles,
                section_config=custom_config,
                local_section_dir=local_section_dir,
                shared_section_dir=shared_section_dir,
                section_path_str=section_path_str,
                title_level=title_level + 1,
                section_flavors=section_flavors,
                section_dependencies=section_dependencies,
            )
        return items, dependencies

    def _process_item(
        self,
        item: str | dict[str, str | None],
        items: list[ContentOrTitle],
        dependencies: Dependencies,
        default_titles: dict[str, str] | None,
        section_config: dict[str, Any],
        local_section_dir: Path,
        shared_section_dir: Path,
        section_path_str: str,
        title_level: int,
        section_flavors: defaultdict[str, set[str]],
        section_dependencies: defaultdict[str, Dependencies],
    ) -> None:
        if isinstance(item, str):
            filename = item
            title = None if default_titles is None else default_titles.get(filename)
        else:
            filename, title = next(iter(item.items()))
        if "excludes" in section_config and filename in section_config["excludes"]:
            return
        if filename.startswith("/"):
            local_path = (self.paths.local_latex_dir / filename[1:]).with_suffix(".tex")
            shared_path = (self.paths.shared_latex_dir / filename[1:]).with_suffix(
                ".tex"
            )
        elif filename.startswith("$"):
            assert title is not None
            self._process_nested_section(
                section_path_str=section_path_str,
                nested_section_path_str=filename,
                flavor=title,
                title_level=title_level,
                section_flavors=section_flavors,
                section_dependencies=section_dependencies,
                items=items,
                dependencies=dependencies,
            )
            return
        else:
            local_path = (local_section_dir / filename).with_suffix(".tex")
            shared_path = (shared_section_dir / filename).with_suffix(".tex")
        if title is not None:
            items.append(Title(title=title, level=title_level))
        local_relative_path = local_path.relative_to(self.paths.current_dir)
        shared_relative_path = shared_path.relative_to(self.paths.shared_dir)
        if local_path.exists():
            items.append(str(PurePosixPath(local_relative_path.with_suffix(""))))
            dependencies.used.add(local_path.resolve())
        elif shared_path.exists():
            items.append(str(PurePosixPath(shared_relative_path.with_suffix(""))))
            dependencies.used.add(shared_path.resolve())
        else:
            dependencies.missing.add(filename)

    def _process_nested_section(
        self,
        section_path_str: str,
        nested_section_path_str: str,
        flavor: str,
        title_level: int,
        section_flavors: defaultdict[str, set[str]],
        section_dependencies: defaultdict[str, Dependencies],
        items: list[ContentOrTitle],
        dependencies: Dependencies,
    ) -> None:
        if nested_section_path_str.startswith("$/"):
            nested_section_path = nested_section_path_str[2:]
        else:
            nested_section_path = f"{section_path_str}/{nested_section_path_str[1:]}"
        parsed_nested_dir = self._parse_section_dir(
            nested_section_path,
            {"flavor": flavor},
            title_level,
            section_flavors,
            section_dependencies,
        )
        assert parsed_nested_dir is not None
        nested_items, nested_dependencies = parsed_nested_dir
        section_flavors[nested_section_path].add(flavor)
        section_dependencies[nested_section_path].update(nested_dependencies)
        items.extend(nested_items)
        dependencies.update(nested_dependencies)

    def _parse_section_file(
        self, section_path: str, config: dict[str, Any], title_level: int
    ) -> tuple[list[ContentOrTitle], Dependencies] | None:
        local_section_file = (self.paths.local_latex_dir / section_path).with_suffix(
            ".tex"
        )
        shared_section_file = (self.paths.shared_latex_dir / section_path).with_suffix(
            ".tex"
        )
        if local_section_file.exists():
            section_file = local_section_file
            relative_path = section_file.relative_to(self.paths.current_dir)
        elif shared_section_file.exists():
            section_file = shared_section_file
            relative_path = section_file.relative_to(self.paths.shared_dir)
        else:
            return None
        config_file = section_file.with_suffix(".yml")
        items: list[ContentOrTitle] = []
        if "title" in config:
            title = config["title"]
        elif config_file.exists():
            title = safe_load(config_file.read_text(encoding="utf8"))["title"]
        else:
            title = None
        if title is not None:
            items.append(Title(title=title, level=title_level))
        items.append(str(PurePosixPath(relative_path.with_suffix(""))))
        dependencies = Dependencies()
        dependencies.used.add(section_file.resolve())
        return items, dependencies


@dataclass(frozen=True)
class Targets(Iterable[Target]):
    targets: list[Target]
    paths: Paths

    def __post_init__(self) -> None:
        missing_dependencies = {
            target.name: target.dependencies.missing
            for target in self.targets
            if target.dependencies.missing
        }
        if missing_dependencies:

            def format_paths(paths: set[str]) -> str:
                return "\n".join(f"    - {p}" for p in paths)

            missing_deps = "\n".join(
                f"  - {k}:\n{format_paths(v)}" for k, v in missing_dependencies.items()
            )
            msg = (
                f"incorrect targets {self.paths.targets}. "
                "Could not find the following dependencies:\n"
                f"{missing_deps}"
            )

            raise DeckzError(msg)

    @classmethod
    def from_file(
        cls, paths: Paths, whitelist: Iterable[str] | None = None
    ) -> "Targets":
        if not paths.targets.exists():
            msg = f"could not find {paths.targets}"
            raise DeckzError(msg)
        content = safe_load(paths.targets.read_text(encoding="utf8"))
        return cls.from_data(data=content, paths=paths, whitelist=whitelist)

    @classmethod
    def from_data(
        cls,
        data: list[dict[str, Any]],
        paths: Paths,
        whitelist: Iterable[str] | None = None,
    ) -> "Targets":
        for target_data in data:
            if target_data["name"] == "all":
                msg = (
                    f"incorrect targets {paths.targets}: "
                    '"all" is a reserved target name'
                )
                raise DeckzError(msg)
        targets = [TargetBuilder(data=target, paths=paths).build() for target in data]
        if whitelist is not None:
            targets = cls._filter_targets(targets, frozenset(whitelist), paths)
        return Targets(targets, paths)

    @staticmethod
    def _filter_targets(
        targets: Iterable[Target], whiteset: Set[str], paths: Paths
    ) -> list[Target]:
        unmatched = whiteset - frozenset(target.name for target in targets)
        if unmatched:
            unmatched_targets = "\n".join(f"  - {name}" for name in unmatched)
            msg = (
                f"incorrect targets {paths.targets}. "
                f"Could not find the following targets:\n{unmatched_targets}"
            )
            raise DeckzError(msg)
        return [target for target in targets if target.name in whiteset]

    def __iter__(self) -> Iterator[Target]:
        return iter(self.targets)

    def __len__(self) -> int:
        return len(self.targets)
