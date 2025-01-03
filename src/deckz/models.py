"""Model classes.

There are several kinds of types defined in this module:

- Simple scalar types to disambiguate multi-usage types, e.g. Path and str:

    - [`IncludePath`][deckz.models.IncludePath]
    - [`UnresolvedPath`][deckz.models.UnresolvedPath]
    - [`ResolvedPath`][deckz.models.ResolvedPath]
    - [`PartName`][deckz.models.PartName]
    - [`FlavorName`][deckz.models.FlavorName]

- Types used to represent deck definitions (typically what's in `deck.yml`). All those \
    classes are defined using the Pydantic library and can be easily instantiated from \
    yaml files:

    - [`NodeInclude`][deckz.models.NodeInclude]
    - [`SectionInclude`][deckz.models.SectionInclude]
    - [`FileInclude`][deckz.models.FileInclude]
    - [`FlavorDefinition`][deckz.models.FlavorDefinition]
    - [`SectionDefinition`][deckz.models.SectionDefinition]
    - [`PartDefinition`][deckz.models.PartDefinition]
    - [`DeckDefinition`][deckz.models.DeckDefinition]

    The only tricky part in those classes is the format used to define includes. The \
    intent is that it should be possible, both to include files and sections, to \
    specify only a path, or a path and a title. The path can be relative to the \
    current element being parsed or to a base directory. This tricky logic is \
    implemented in the `_normalize_include` function.

    The yaml syntax used is the following:

    - for a file without a title

            path/relative/to/current/element
            /path/relative/to/basedir

    - for a file with a title

            path/relative/to/current/element: title
            /path/relative/to/basedir: title

    - for a section without a title

            $path/relative/to/current/element@flavor
            $/path/relative/to/basedir@flavor

    - for a section with a title

            $path/relative/to/current/element@flavor: title
            $/path/relative/to/basedir@flavor: title

- Types used to represent and process instantiated decks (in opposition to deck \
    definitions):

    - [`Deck`][deckz.models.Deck]
    - [`Part`][deckz.models.Part]
    - [`Section`][deckz.models.Section]
    - [`File`][deckz.models.File]
    - [`Node`][deckz.models.Node]

    A [`Deck`][deckz.models.Deck] deck is comprised of one or several \
    [`Part`][deckz.models.Part]s, themselves comprised of \
    [`Node`][deckz.models.Node]s ([`Section`][deckz.models.Section]s and \
    [`File`][deckz.models.File]s). [`Node`][deckz.models.Node]s have an `accept` \
    method that allows for dispatching processing when writing deck processing code, \
    following the \
    [Visitor](https://refactoring.guru/design-patterns/visitor/python/example) pattern.

    The [`NodeVisitor`][deckz.models.NodeVisitor] protocol can be used to specify the \
    types in play when writing such code.

- Types representing slides that will be used by the rendering component (jinja2 by \
    default):

    - [`Title`][deckz.models.Title]
    - [`Content`][deckz.models.Content]
    - [`TitleOrContent`][deckz.models.TitleOrContent]
    - [`PartSlides`][deckz.models.PartSlides]

- Type representing the output of compilation step (output, error, etc):

    - [`CompileResult`][deckz.models.CompileResult]

- Type to collect stats on assets:

    - [`AssetsUsage`][deckz.models.AssetsUsage]
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Annotated, Any, NewType, Protocol

from pydantic import BaseModel
from pydantic.functional_validators import BeforeValidator

########################################################################################
# Simple scalars                                                                       #
########################################################################################

IncludePath = NewType("IncludePath", PurePath)
"""Derived from PurePath to be used only to specify an include in a deck definition."""

UnresolvedPath = NewType("UnresolvedPath", PurePath)
"""Derived from PurePath to represent any path that has not been resolved yet.

Resolving in deckz code means mainly picking between two options for a given resource: \
loading it from the shared directory or from the local directory.
"""

ResolvedPath = NewType("ResolvedPath", Path)
"""Derived from Path to represent any path that has already been resolved.

Resolving in deckz code means mainly picking between two options for a given resource: \
loading it from the shared directory or from the local directory.
"""

PartName = NewType("PartName", str)
"""Derived from str to represent specifically a part name."""

FlavorName = NewType("FlavorName", str)
"""Derived from str to represent specifically a flavor name."""


########################################################################################
# Deck definition types                                                                #
########################################################################################


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


########################################################################################
# Deck representation and processing types                                             #
########################################################################################


class NodeVisitor[**P, T](Protocol):
    """Dispatch actions on [`Node`][deckz.models.Node]s."""

    def visit_file(self, file: "File", *args: P.args, **kwargs: P.kwargs) -> T:
        """Dispatched method for [`File`][deckz.models.File]s."""
        ...

    def visit_section(self, section: "Section", *args: P.args, **kwargs: P.kwargs) -> T:
        """Dispatched method for [`Section`][deckz.models.Section]s."""
        ...


@dataclass
class Node(ABC):
    """Node in a section or part.

    A node is anything that can be included in a [`Part`][deckz.models.Part] or a \
    [`Section`][deckz.models.Section]: it can be either a \
    [`Section`][deckz.models.Section] or a [`File`][deckz.models.File].
    """

    title: str | None
    unresolved_path: UnresolvedPath
    # resolved_path and parsing_error could benefit from a refactoring using something
    # like Either because we cannot have both a ResolvedPath and a parsing_error at the
    # same time.
    resolved_path: ResolvedPath
    parsing_error: str | None

    @abstractmethod
    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the corresponding \
            [`visit_file`][deckz.models.NodeVisitor.visit_file] or \
            [`visit_section`][deckz.models.NodeVisitor.visit_section] method of \
            the visitor.
        """
        raise NotImplementedError


@dataclass
class File(Node):
    """File in a section or part."""

    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the \
            [`visit_file`][deckz.models.NodeVisitor.visit_file] method of the \
            visitor.
        """
        return visitor.visit_file(self, *args, **kwargs)


@dataclass
class Section(Node):
    """Section in a section or part."""

    flavor: FlavorName
    """Name of the flavor of the section."""

    nodes: list[Node]
    """Nodes included in the section."""

    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the \
            [`visit_section`][deckz.models.NodeVisitor.visit_section] method of \
            the visitor.
        """
        return visitor.visit_section(self, *args, **kwargs)


@dataclass
class Part:
    """Part in a deck."""

    title: str | None
    """Title of the part."""

    nodes: list[Node]
    """Nodes included in the part."""


@dataclass
class Deck:
    """Top of the hierarchy for deck parsing."""

    name: str
    """The name of the deck. Will be a part of the output file name."""

    parts: dict[PartName, Part]
    """Parts included in the deck."""

    def filter(self, whitelist: Iterable[PartName]) -> None:
        """Filter out the parts that don't have their name listed in `whitelist`.

        Args:
            whitelist: Parts to keep.

        Raises:
            ValueError: Raised if an element of `whitelist` matches no part name in \
                the deck.
        """
        if frozenset(whitelist).difference(self.parts):
            msg = "provided whitelist has part names not in the deck"
            raise ValueError(msg)
        to_remove = frozenset(self.parts).difference(whitelist)
        for part_name in to_remove:
            del self.parts[part_name]


########################################################################################
# Slides representation                                                                #
########################################################################################


@dataclass(frozen=True)
class Title:
    """Define a title slide and its level.

    The lower the level, the more important the title. Similar to how h1 in HTML is \
    a more important title than h2.
    """

    title: str
    """The title string to display during rendering."""

    level: int
    """The level of the title."""


Content = str
"""Alias to string to denote slide content path."""

TitleOrContent = Title | Content
"""Alias to title or content to denote any slide."""


@dataclass(frozen=True)
class PartSlides:
    """Title and slides comprising a part."""

    title: str | None
    """Title of the part."""

    sections: list[TitleOrContent] = field(default_factory=list)
    """Slides of the part."""


########################################################################################
# Compilation representation                                                           #
########################################################################################


@dataclass(frozen=True)
class CompileResult:
    """Result of a compilation."""

    ok: bool
    """True if the compilation finished with a non-error code, False otherwise."""

    stdout: str | None = ""
    """The complete stdout output during compilation."""

    stderr: str | None = ""
    """The complete stderr output during compilation."""


########################################################################################
# Assets usage stats                                                                   #
########################################################################################


type AssetsMetadata = dict[str, tuple[dict[str, Any] | None, ...]]
"""Assets and the number of time they appear in a given render."""
