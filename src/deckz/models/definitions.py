from pathlib import PurePath
from typing import Annotated

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator

from .scalars import FlavorName, IncludePath, PartName


class NodeInclude(BaseModel):
    path: IncludePath
    title: str | None = None


class SectionInclude(NodeInclude):
    flavor: FlavorName


class FileInclude(NodeInclude):
    pass


def _normalize_include(
    v: str | dict[str, str] | NodeInclude,
) -> NodeInclude:
    if isinstance(v, NodeInclude):
        return v
    if isinstance(v, str):
        left = v
        title_unset = True
    else:
        assert len(v) == 1
        left, title = next(iter(v.items()))
        title_unset = False
    if left.startswith("$"):
        path, flavor = left[1:].split("@")
    else:
        path = left
        flavor = None
    if flavor is None and title_unset:
        return FileInclude(path=IncludePath(PurePath(path)))
    if flavor is None:
        return FileInclude(path=IncludePath(PurePath(path)), title=title)
    if title_unset:
        return SectionInclude(
            path=IncludePath(PurePath(path)), flavor=FlavorName(flavor)
        )
    return SectionInclude(
        path=IncludePath(PurePath(path)), flavor=FlavorName(flavor), title=title
    )


class FlavorDefinition(BaseModel):
    name: FlavorName
    title: str | None = None
    includes: list[Annotated[NodeInclude, BeforeValidator(_normalize_include)]]


class SectionDefinition(BaseModel):
    title: str
    default_titles: dict[IncludePath, str] | None = None
    flavors: list[FlavorDefinition]


class PartDefinition(BaseModel):
    name: PartName
    title: str | None = None
    sections: list[Annotated[NodeInclude, BeforeValidator(_normalize_include)]]


class DeckDefinition(BaseModel):
    name: str
    parts: list[PartDefinition]
