"""Content stamps: whether a built file is up to date with what it was built from.

A file's modification time can't tell: a git checkout gives every file it
writes the current time, so after a clone, a branch switch or a `git stash`,
sources look newer than the outputs built from them (and committed outputs
older than their sources), and copying outputs into another checkout (a
worktree) changes their times too. A stamp is instead a digest of the
inputs' bytes, written next to the output once it's built
(`<output>.stamp`): the output is up to date while its stamp matches the
digest of its inputs as they are now, whatever their times.

An assets builder (see `AssetsBuilderProtocol`) uses it like this:

```python
stamp = digest([source, *shared_inputs])
if not is_fresh(output, stamp, [source, *shared_inputs]):
    build(source, output)
    write_stamp(output, stamp)
```

When the outputs are committed, so are their stamps: a fresh clone then
rebuilds nothing.
"""

import ast
import hashlib
from collections.abc import Iterable
from pathlib import Path


def stamp_path(output: Path) -> Path:
    """Where `output`'s stamp is written.

    Returns:
        `<output>.stamp`, next to it.
    """
    return output.with_name(f"{output.name}.stamp")


def digest(inputs: Iterable[Path], *extra: str) -> str:
    """The digest of `inputs`' bytes, in order, then of `extra`.

    Args:
        inputs: The files an output is built from. Only their bytes count, \
            not their paths, so the digest is the same in every checkout.
        extra: Anything else the output depends on: a setting (its \
            language, a quality), or the digest of inputs several outputs \
            share, computed once.

    Returns:
        The digest, as a hex string.
    """
    hasher = hashlib.sha256()
    for data in (
        *(path.read_bytes() for path in inputs),
        *(value.encode("utf8") for value in extra),
    ):
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
    return hasher.hexdigest()


def is_fresh(output: Path, stamp: str, inputs: Iterable[Path] = ()) -> bool:
    """Whether `output` exists and was built from inputs digesting to `stamp`.

    An output with no stamp yet, built before its builder wrote stamps, is \
    taken as up to date if it's newer than every one of `inputs` (the old \
    rule), and stamped: without that, the first build after the switch \
    would rebuild everything (every video included).

    Args:
        output: The built file.
        stamp: The `digest` of what it would be built from now.
        inputs: The files `stamp` digests, for an output with no stamp yet.

    Returns:
        True if `output` needs no rebuild.
    """
    if not output.is_file():
        return False
    try:
        return stamp_path(output).read_text(encoding="utf8").strip() == stamp
    except FileNotFoundError:
        pass
    inputs = tuple(inputs)
    if not inputs or output.stat().st_mtime_ns < max(
        path.stat().st_mtime_ns for path in inputs
    ):
        return False
    write_stamp(output, stamp)
    return True


def write_stamp(output: Path, stamp: str) -> None:
    """Record that `output` was just built from inputs digesting to `stamp`."""
    stamp_path(output).write_text(f"{stamp}\n", encoding="utf8")


def python_sources(module: Path, roots: Iterable[Path]) -> tuple[Path, ...]:
    """`module` and every module under `roots` it imports, transitively.

    The inputs of an output a Python module builds (a plot, a video): an \
    edit of a helper it imports (a shared base class, a plotting utility) \
    rebuilds it too. Imports are read with `ast`, not run: one through \
    `importlib`, or a data file the module reads, isn't covered.

    Args:
        module: The module's file.
        roots: The directories absolute imports resolve against (those on \
            `sys.path` when it runs); relative imports resolve against the \
            importing module's package.

    Returns:
        `module`, then the modules it imports that are files under \
        `roots` (the packages' `__init__.py` included), sorted.
    """
    roots = tuple(roots)
    found = {module}
    pending = [module]
    while pending:
        current = pending.pop()
        for node in ast.walk(ast.parse(current.read_bytes())):
            if isinstance(node, ast.Import):
                bases, names = roots, [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = f"{node.module}." if node.module else ""
                # `from a import b` imports `a`, and `a.b` if it's a module.
                names = [
                    node.module or "",
                    *(prefix + alias.name for alias in node.names),
                ]
                bases = roots
                if node.level:
                    bases = (current.parents[node.level - 1],)
            else:
                continue
            for base in bases:
                files = _module_files(base, names)
                if isinstance(node, ast.ImportFrom) and node.level:
                    files.append(base / "__init__.py")
                for path in filter(Path.is_file, files):
                    if path not in found:
                        found.add(path)
                        pending.append(path)
    return (module, *sorted(found - {module}))


def _module_files(base: Path, names: Iterable[str]) -> list[Path]:
    """The files importing each of `names` from `base` would run.

    Returns:
        Candidates, there or not: `import a.b` runs `a/__init__.py`, then \
        `a/b.py` or `a/b/__init__.py`.
    """
    files = []
    for name in filter(None, names):
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            path = base.joinpath(*parts[:i])
            files += [path / "__init__.py", path.with_name(f"{path.name}.py")]
    return files
