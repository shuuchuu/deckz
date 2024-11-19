from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.functional_validators import BeforeValidator
from typing_extensions import ParamSpec
from yaml import safe_load

from ..configuring.paths import Paths

_P = ParamSpec("_P")
_T = TypeVar("_T", covariant=True)


class Visitor(Protocol[_P, _T]):
    def visit_file(self, file: "File", *args: _P.args, **kwargs: _P.kwargs) -> _T: ...
    def visit_section(
        self, section: "Section", *args: _P.args, **kwargs: _P.kwargs
    ) -> _T: ...


@dataclass
class File:
    title: str | None
    logical_path: Path
    path: Path
    parsing_error: str | None

    def accept(
        self, visitor: Visitor[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        return visitor.visit_file(self, *args, **kwargs)


@dataclass
class Section:
    title: str | None
    logical_path: Path
    path: Path
    flavor: str
    children: list["File | Section"]
    parsing_error: str | None

    def accept(
        self, visitor: Visitor[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        return visitor.visit_section(self, *args, **kwargs)


@dataclass
class Part:
    title: str | None
    nodes: list[File | Section]


@dataclass
class Deck:
    acronym: str
    parts: dict[str, Part]

    def filter(self, whitelist: Iterable[str]) -> None:
        if frozenset(whitelist).difference(self.parts):
            msg = "provided whitelist has part names not in the deck"
            raise ValueError(msg)
        to_remove = frozenset(self.parts).difference(whitelist)
        for part_name in to_remove:
            del self.parts[part_name]


class SectionInclude(BaseModel):
    flavor: str
    path: Path
    title: str | None = None
    title_unset: bool = False


class FileInclude(BaseModel):
    path: Path
    title: str | None = None
    title_unset: bool = False


def _normalize_flavor_content(v: str | dict[str, str]) -> FileInclude | SectionInclude:
    if isinstance(v, str):
        return FileInclude(path=Path(v))
    assert len(v) == 1
    path, flavor_or_title = next(iter(v.items()))
    if path.startswith("$"):
        return SectionInclude(flavor=flavor_or_title, path=Path(path[1:]))
    if flavor_or_title is None:
        return FileInclude(path=Path(path), title_unset=True)
    return FileInclude(path=Path(path), title=flavor_or_title)


class SectionDefinition(BaseModel):
    title: str
    default_titles: dict[Path, str] | None = None
    flavors: dict[
        str,
        list[
            Annotated[
                SectionInclude | FileInclude, BeforeValidator(_normalize_flavor_content)
            ]
        ],
    ]
    version: int | None = None


def _normalize_part_content(v: str | dict[str, str]) -> FileInclude | SectionInclude:
    if isinstance(v, str):
        return FileInclude(path=Path(v))
    if isinstance(v, dict) and "path" not in v:
        assert len(v) == 1
        path, flavor = next(iter(v.items()))
        return SectionInclude(path=Path(path), flavor=flavor, title=None)
    if "flavor" not in v:
        return FileInclude(path=Path(v["path"]), title=v.get("title"))
    return SectionInclude(
        path=Path(v["path"]), flavor=v["flavor"], title=v.get("title")
    )


class PartDefinition(BaseModel):
    name: str
    title: str | None = None
    sections: list[
        Annotated[
            SectionInclude | FileInclude, BeforeValidator(_normalize_part_content)
        ]
    ]


class DeckConfig(BaseModel, extra="allow"):
    deck_acronym: str


class DeckParser:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def parse(self) -> Deck:
        content = safe_load(self._paths.deck_config.read_text(encoding="utf8"))
        deck_config = DeckConfig.model_validate(content)

        content = safe_load(self._paths.targets.read_text(encoding="utf8"))
        adapter = TypeAdapter(list[PartDefinition])
        part_definitions = adapter.validate_python(content)

        return Deck(
            acronym=deck_config.deck_acronym, parts=self.parse_parts(part_definitions)
        )

    def parse_parts(self, part_definitions: list[PartDefinition]) -> dict[str, Part]:
        parts = {}
        for part_definition in part_definitions:
            part_nodes: list[File | Section] = []
            for node_include in part_definition.sections:
                if isinstance(node_include, SectionInclude):
                    part_nodes.append(
                        self._parse_section(
                            base_logical_path=Path("/"),
                            logical_path=node_include.path,
                            title=node_include.title,
                            flavor=node_include.flavor,
                        )
                    )
                else:
                    part_nodes.append(
                        self._parse_file(
                            base_logical_path=Path("/"),
                            logical_path=node_include.path,
                            title=node_include.title,
                        )
                    )
            parts[part_definition.name] = Part(
                title=part_definition.title,
                nodes=part_nodes,
            )
        return parts

    def _parse_section(
        self,
        base_logical_path: Path,
        logical_path: Path,
        title: str | None,
        flavor: str,
    ) -> Section:
        logical_path = self._compute_logical_path(base_logical_path, logical_path)
        section = Section(
            title=title,
            logical_path=logical_path,
            path=logical_path,
            parsing_error=None,
            flavor=flavor,
            children=[],
        )
        resolved_path = self._resolve(logical_path, resolve_target="dir")
        if resolved_path:
            section.path = resolved_path
        else:
            section.parsing_error = f"unresolvable section path {logical_path}"
            return section
        definition_logical_path = (logical_path / logical_path.name).with_suffix(".yml")
        definition_resolved_path = self._resolve(
            definition_logical_path.with_suffix(".yml"), "file"
        )
        if definition_resolved_path is None:
            section.parsing_error = (
                f"unresolvable section definition path {definition_logical_path}"
            )
            return section
        try:
            content = safe_load(definition_resolved_path.read_text(encoding="utf8"))
        except Exception as e:
            section.parsing_error = f"{e}"
            return section
        try:
            section_definition = SectionDefinition.model_validate(content)
        except ValidationError as e:
            section.parsing_error = f"{e}"
            return section
        if section.title is None:
            section.title = section_definition.title
        if flavor not in section_definition.flavors:
            section.parsing_error = f"flavor {flavor} not found"
            return section
        for node_include in section_definition.flavors[flavor]:
            if node_include.title:
                title = node_include.title
            elif (
                not node_include.title_unset
                and section_definition.default_titles
                and node_include.path in section_definition.default_titles
            ):
                title = section_definition.default_titles[node_include.path]
            else:
                title = None
            if isinstance(node_include, FileInclude):
                section.children.append(
                    self._parse_file(
                        base_logical_path=logical_path,
                        logical_path=node_include.path,
                        title=title,
                    )
                )
            else:
                section.children.append(
                    self._parse_section(
                        base_logical_path=logical_path,
                        logical_path=node_include.path,
                        title=title,
                        flavor=node_include.flavor,
                    )
                )
        return section

    def _parse_file(
        self, base_logical_path: Path, logical_path: Path, title: str | None
    ) -> File:
        logical_path = self._compute_logical_path(base_logical_path, logical_path)
        file = File(
            title=title,
            logical_path=logical_path,
            path=logical_path,
            parsing_error=None,
        )
        resolved_path = self._resolve(logical_path.with_suffix(".tex"), "file")
        if resolved_path:
            file.path = resolved_path
        else:
            file.parsing_error = f"unresolvable file path {logical_path}"
        return file

    @staticmethod
    def _compute_logical_path(base_logical_path: Path, logical_path: Path) -> Path:
        return logical_path if logical_path.root else base_logical_path / logical_path

    def _resolve(
        self, logical_path: Path, resolve_target: Literal["file", "dir"]
    ) -> Path | None:
        relative_logical_path = logical_path.relative_to("/")
        local_path = self._paths.local_latex_dir / relative_logical_path
        shared_path = self._paths.shared_latex_dir / relative_logical_path
        existence_tester = Path.is_file if resolve_target == "file" else Path.is_dir
        for path in [local_path, shared_path]:
            if existence_tester(path):
                return path.resolve()
        return None
