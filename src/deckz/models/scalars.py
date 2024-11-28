from pathlib import Path, PurePath
from typing import NewType

IncludePath = NewType("IncludePath", PurePath)
UnresolvedPath = NewType("UnresolvedPath", PurePath)
ResolvedPath = NewType("ResolvedPath", Path)
PartName = NewType("PartName", str)
FlavorName = NewType("FlavorName", str)
