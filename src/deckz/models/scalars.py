"""Model NewTypes to disambiguate multi-usage types."""

from pathlib import Path, PurePath
from typing import NewType

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
