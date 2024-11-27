from pathlib import PurePath
from typing import Annotated

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator

from .scalars import FlavorName, IncludePath, PartName


class SectionInclude(BaseModel):
    flavor: FlavorName
    path: IncludePath
    title: str | None = None
    title_unset: bool = False


class FileInclude(BaseModel):
    path: IncludePath
    title: str | None = None
    title_unset: bool = False


def _normalize_flavor_content(v: str | dict[str, str]) -> FileInclude | SectionInclude:
    if isinstance(v, str):
        return FileInclude(path=IncludePath(PurePath(v)))
    assert len(v) == 1
    path, flavor_or_title = next(iter(v.items()))
    if path.startswith("$"):
        return SectionInclude(
            flavor=FlavorName(flavor_or_title), path=IncludePath(PurePath(path[1:]))
        )
    if flavor_or_title is None:
        return FileInclude(path=IncludePath(PurePath(path)), title_unset=True)
    return FileInclude(path=IncludePath(PurePath(path)), title=flavor_or_title)


class SectionDefinition(BaseModel):
    title: str
    default_titles: dict[IncludePath, str] | None = None
    flavors: dict[
        FlavorName,
        list[
            Annotated[
                SectionInclude | FileInclude, BeforeValidator(_normalize_flavor_content)
            ]
        ],
    ]
    version: int | None = None


def _normalize_part_content(v: str | dict[str, str]) -> FileInclude | SectionInclude:
    if isinstance(v, str):
        return FileInclude(path=IncludePath(PurePath(v)))
    if isinstance(v, dict) and "path" not in v:
        assert len(v) == 1
        path, flavor = next(iter(v.items()))
        return SectionInclude(
            path=IncludePath(PurePath(path)), flavor=FlavorName(flavor), title=None
        )
    if "flavor" not in v:
        return FileInclude(path=IncludePath(PurePath(v["path"])), title=v.get("title"))
    return SectionInclude(
        path=IncludePath(PurePath(v["path"])),
        flavor=FlavorName(v["flavor"]),
        title=v.get("title"),
    )


class PartDefinition(BaseModel):
    name: PartName
    title: str | None = None
    sections: list[
        Annotated[
            SectionInclude | FileInclude, BeforeValidator(_normalize_part_content)
        ]
    ]


class DeckConfig(BaseModel, extra="allow"):
    deck_acronym: str
