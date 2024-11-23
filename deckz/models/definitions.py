from pathlib import Path
from typing import Annotated

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator


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
