"""Model classes to define decks.

All classes in this module are using the Pydantic library and can be easily \
instantiated from yaml files.

The only tricky part in those classes is the format used to define includes. The \
intent is that it should be possible, both to include files and sections, to specify \
only a path, or a path and a title. The path can be relative to the current element \
being parsed or to a base directory.

The yaml syntax used is the following:

- for a path without a title

        path/relative/to/current/element
        /path/relative/to/basedir

- for a path with a title

        path/relative/to/current/element: title
        /path/relative/to/basedir: title

- for a section without a title

        $path/relative/to/current/element@flavor
        $/path/relative/to/basedir@flavor

- for a section with a title

        $path/relative/to/current/element@flavor: title
        $/path/relative/to/basedir@flavor: title

"""

from pathlib import PurePath
from typing import Annotated

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator

from .scalars import FlavorName, IncludePath, PartName


class NodeInclude(BaseModel):
    """Specify a file or section include."""

    path: IncludePath
    """Path of the file or section to include."""

    title: str | None = None
    """The title of the node. Will override the ones defined in the section \
    definition and the flavor definition.
    """


class SectionInclude(NodeInclude):
    """Specify a section to include.

    See its parent for further details on the available attributes.
    """

    flavor: FlavorName
    """Flavor of the section to include."""


class FileInclude(NodeInclude):
    """Specify a file to include.

    See its parent for further details on the available attributes.
    """


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
    """Specify the different attributes of a flavor."""

    name: FlavorName
    """The name of the flavor. Used in parts and sections definitions."""

    title: str | None = None
    """The title of the section. Will override the one defined in the section \
    definition."""

    includes: list[Annotated[NodeInclude, BeforeValidator(_normalize_include)]]
    """The includes pointing to the sections and files in this section."""


class SectionDefinition(BaseModel):
    """Specify the different attributes of a section."""

    title: str
    """The title of the section. Will be given as input to the rendering code."""

    default_titles: dict[IncludePath, str] | None = None
    """Default titles to use for the includes of the section."""

    flavors: list[FlavorDefinition]
    """Different flavors of the section (each flavor can define a different \
    title and a different list of includes)."""


class PartDefinition(BaseModel):
    """Specify the different attributes of a deck part."""

    name: PartName
    """The name of the part. Will be a part of the output file name if partial \
    outputs are built."""

    title: str | None = None
    """The title of the part. Will be given as input to the rendering code."""

    sections: list[Annotated[NodeInclude, BeforeValidator(_normalize_include)]]
    """The includes pointing to the sections and files in this part."""


class DeckDefinition(BaseModel):
    """Specify the different attributes of a deck."""

    name: str
    """The name of the deck. Will be a part of the output file name."""

    parts: list[PartDefinition]
    """The definition of each part of the deck."""
