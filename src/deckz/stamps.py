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

An output missing or stale here may be fresh in another checkout of the
repository (the main one, a worktree: `deckz worktree`), built or rendered
there from the same sources: `is_fresh` then copies it, with its stamp, rather
than have it built again. A stamp digests bytes, never paths, so a copy whose
stamp matches is exactly what a build here would make: a video rendered in the
main checkout is published from a worktree, a figure a worktree compiled
serves the others.

A checkout going away (`deckz worktree remove`) sets aside in the
repository's git directory the outputs only it holds (`set_aside`), so that
the main checkout still adopts them once its sources catch up (a pull): the
store (`<git common dir>/deckz/renders/<stamp>/`, each output at its path in
the checkout, with its stamp and companions) is searched after the other
checkouts. `prune` drops what a checkout holds again, and what's older than
`STORE_DAYS`.
"""

import ast
import hashlib
from collections.abc import Iterable
from logging import getLogger
from os import utime
from pathlib import Path
from shutil import rmtree
from time import time

from .utils import copy_file_if_changed, write_atomic

_logger = getLogger(__name__)

STORE_DAYS = 30
"""How long an output set aside is kept for a checkout to adopt it."""


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


def is_fresh(
    output: Path,
    stamp: str,
    inputs: Iterable[Path] = (),
    companions: Iterable[Path] = (),
) -> bool:
    """Whether `output` exists and was built from inputs digesting to `stamp`.

    An output with no stamp yet, built before its builder wrote stamps, is \
    taken as up to date if it's newer than every one of `inputs` (the old \
    rule), and stamped: without that, the first build after the switch \
    would rebuild everything (every video included).

    An output missing or stale is first looked for in the repository's other \
    checkouts (`adopt`): one fresh there is copied here, and up to date.

    Args:
        output: The built file.
        stamp: The `digest` of what it would be built from now.
        inputs: The files `stamp` digests, for an output with no stamp yet.
        companions: Files the build writes next to `output` and copied with \
            it from another checkout (a video's poster), which must exist there.

    Returns:
        True if `output` needs no rebuild.
    """
    if output.is_file():
        try:
            if stamp_path(output).read_text(encoding="utf8").strip() == stamp:
                return True
        except FileNotFoundError:
            inputs = tuple(inputs)
            if inputs and output.stat().st_mtime_ns >= max(
                path.stat().st_mtime_ns for path in inputs
            ):
                write_stamp(output, stamp)
                return True
    return adopt(output, stamp, companions)


def adopt(output: Path, stamp: str, companions: Iterable[Path] = ()) -> bool:
    """Copy `output` from another checkout where it's stamped `stamp`.

    The main checkout is looked in first, then the worktrees, in git's \
    order, then the outputs set aside (`set_aside`): the first whose copy of \
    `output` (and of each of `companions`) exists with that stamp is copied, \
    the stamp last, so that `output` is never stamped over another file. A \
    copy rebuilt there meanwhile (its stamp changed during the copy) isn't \
    stamped here: it's built again.

    Args:
        output: The output, in this checkout.
        stamp: The `digest` of what it would be built from here.
        companions: Files next to `output` copied with it.

    Returns:
        Whether it was copied.
    """
    root = _checkout(output)
    if root is None:
        return False
    relative = output.relative_to(root)
    files = [relative, *(path.relative_to(root) for path in companions)]
    others = _checkouts(root)
    if (store := _store(root)) is not None:
        others.append(store / stamp)
    for other in others:
        if other == root.resolve():
            continue
        found = stamp_path(other / relative)
        if _read(found) != stamp or not all((other / f).is_file() for f in files):
            continue
        # This checkout's stamp isn't about the files being replaced.
        stamp_path(output).unlink(missing_ok=True)
        for file in reversed(files):
            copy_file_if_changed(other / file, root / file)
        if _read(found) != stamp:
            continue
        write_stamp(output, stamp)
        if store is not None and other.parent == store:
            _logger.info("%s: copied from the builds set aside", relative)
        else:
            _logger.info("%s: copied from %s, where it's up to date", relative, other)
        return True
    return False


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf8").strip()
    except OSError:
        return None


def _checkout(path: Path) -> Path | None:
    """The root of the git checkout holding `path` (which may not exist yet).

    Returns:
        The first of its parents holding a `.git`, or None.
    """
    return next((p for p in path.parents if (p / ".git").exists()), None)


def _common_dir(root: Path) -> Path | None:
    """The git directory the checkouts of `root`'s repository share.

    Read from git's own files, without running git (a build may ask for \
    hundreds of outputs): `.git` is the main checkout's git directory, or a \
    worktree's `gitdir:` file pointing to its own one, whose `commondir` \
    leads to the main one.

    Returns:
        It, or None if `root` has no readable `.git`.
    """
    dot_git = root / ".git"
    try:
        if dot_git.is_dir():
            return dot_git
        text = dot_git.read_text(encoding="utf8").strip()
        own = (root / text.removeprefix("gitdir:").strip()).resolve()
        commondir = (own / "commondir").read_text(encoding="utf8").strip()
        return (own / commondir).resolve()
    except OSError:
        return None


def _store(root: Path) -> Path | None:
    """Where the outputs set aside go: in the shared git directory.

    Returns:
        `<git common dir>/deckz/renders`, or None outside a repository.
    """
    common = _common_dir(root)
    return None if common is None else common / "deckz" / "renders"


def _checkouts(root: Path) -> list[Path]:
    """Every checkout of the repository `root` is a checkout of.

    The shared git directory (`_common_dir`) lists each worktree's own \
    under `worktrees/`.

    Returns:
        The main checkout's root (unless the repository is bare), then each \
        worktree's that exists.
    """
    common = _common_dir(root)
    if common is None:
        return []
    found = [common.parent] if common.name == ".git" else []
    entries = common / "worktrees"
    for entry in sorted(entries.iterdir()) if entries.is_dir() else ():
        gitdir = _read(entry / "gitdir")
        if gitdir and (checkout := Path(gitdir).parent).is_dir():
            found.append(checkout)
    return found


def held_elsewhere(root: Path, relative: Path, stamp: str) -> bool:
    """Whether another checkout than `root`, or the store, has it stamped `stamp`.

    Args:
        root: The checkout asking.
        relative: The output's path in a checkout.
        stamp: Its stamp in `root`.

    Returns:
        True if one does: no need to set it aside.
    """
    others = _checkouts(root)
    if (store := _store(root)) is not None:
        others.append(store / stamp)
    return any(
        other != root.resolve()
        and (other / relative).is_file()
        and _read(stamp_path(other / relative)) == stamp
        for other in others
    )


def set_aside(root: Path, output: Path, companions: Iterable[Path] = ()) -> None:
    """Keep `output`, stamped, for another checkout to adopt once `root` is gone.

    Copied into the store (see the module docstring) with its stamp, last, \
    and `companions`. The entry's time is reset: `prune` keeps it \
    `STORE_DAYS` from now.

    Args:
        root: The checkout holding `output`.
        output: The output, stamped.
        companions: Files next to `output` that go with it.

    Raises:
        ValueError: If `output` has no stamp, or `root` is in no repository.
    """
    stamp = _read(stamp_path(output))
    store = _store(root)
    if stamp is None or store is None:
        msg = f"{output} has no stamp, or {root} is in no repository"
        raise ValueError(msg)
    entry = store / stamp
    for file in (*companions, output, stamp_path(output)):
        copy_file_if_changed(file, entry / file.relative_to(root))
    utime(entry)


def prune(root: Path, days: int = STORE_DAYS) -> list[str]:
    """Drop the outputs set aside that a checkout holds, or older than `days`.

    Returns:
        The paths dropped, relative to their checkout.
    """
    store = _store(root)
    if store is None or not store.is_dir():
        return []
    checkouts = _checkouts(root)
    dropped = []
    for entry in sorted(store.iterdir()):
        outputs = [
            found.with_name(found.name.removesuffix(".stamp")).relative_to(entry)
            for found in entry.rglob("*.stamp")
        ]
        held = all(
            any(
                (other / relative).is_file()
                and _read(stamp_path(other / relative)) == entry.name
                for other in checkouts
            )
            for relative in outputs
        )
        if held or entry.stat().st_mtime < time() - days * 86400:
            rmtree(entry)
            dropped.extend(str(relative) for relative in outputs)
    return dropped


def write_stamp(output: Path, stamp: str) -> None:
    """Record that `output` was just built from inputs digesting to `stamp`.

    The stamp is written atomically: a stamp cut short by a failure, or read \
    while it's written, never matches.
    """
    write_atomic(stamp_path(output), f"{stamp}\n".encode())


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
