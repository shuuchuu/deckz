"""Compare fr/en lab notebook pairs, and find notebooks missing a language.

A translation may change comments, string literals, and identifiers, as long
as each fr name gets the same en name throughout a cell: `code_difference`
looks for anything beyond that.
"""

import io
import json
import keyword
import tokenize
from collections.abc import Iterator, Sequence
from pathlib import Path

from .notebook import cell_source

LANGS = ("fr", "en")

FSTRING_START = getattr(tokenize, "FSTRING_START", -1)
FSTRING_END = getattr(tokenize, "FSTRING_END", -1)


def variants(notebooks_dir: Path) -> dict[Path, set[str]]:
    """Find every lab notebook.

    Returns:
        Each `<lab-dir>/<type>` stem, mapped to the languages it has a \
        notebook in.
    """
    found: dict[Path, set[str]] = {}
    for path in sorted(notebooks_dir.rglob("*.ipynb")):
        if ".ipynb_checkpoints" in path.parts:
            continue
        kind, _, lang = path.stem.rpartition("-")
        found.setdefault(path.parent / kind, set()).add(lang)
    return found


def missing_notebooks(notebooks_dir: Path) -> Iterator[Path]:
    """Every `<lab-dir>/<type>-<lang>.ipynb` missing one language's notebook.

    Yields:
        The missing notebook's path, relative to `notebooks_dir`.
    """
    for stem, langs in variants(notebooks_dir).items():
        for lang in LANGS:
            if lang not in langs:
                rel = stem.relative_to(notebooks_dir)
                yield rel.parent / f"{rel.name}-{lang}.ipynb"


def code_tokens(code: str) -> list[str] | None:
    """Strip what a translation changes from a code cell.

    A whole f-string counts as one string literal: the expressions inside
    one follow the language's grammar ("1 arbre", "1 tree" but "0 trees").
    So does a run of literals (`"Yes": "Oui", "No": "Non"`): data a
    translation may reshape, e.g. a mapping of English values that only the
    fr side needs.

    Returns:
        The cell's tokens, without comments, every string literal or run of \
        them as `S`, or None if the cell doesn't tokenize.
    """
    lines = [
        # Shell lines and magics aren't Python: tokenize them as a plain string.
        repr(line) if line.lstrip().startswith(("!", "%")) else line
        for line in code.splitlines()
    ]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    kept: list[str] = []
    depth = 0
    for token in tokens:
        if token.type == FSTRING_START:
            depth += 1
            if depth == 1:
                kept.append("S")
        elif token.type == FSTRING_END:
            depth -= 1
        elif depth:
            continue
        elif token.type == tokenize.STRING:
            kept.append("S")
        elif token.type not in {
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.ENDMARKER,
        }:
            kept.append(token.string)
    return collapse_literal_runs(kept)


def collapse_literal_runs(tokens: list[str]) -> list[str]:
    """Merge each run of string literals and the `,`/`:` after them into one `S`.

    Returns:
        The tokens, with each such run as a single `S`.
    """
    collapsed: list[str] = []
    for token in tokens:
        if not (token in {"S", ",", ":"} and collapsed and collapsed[-1] == "S"):
            collapsed.append(token)
    return collapsed


def is_name(token: str) -> bool:
    return token.isidentifier() and not keyword.iskeyword(token)


def code_difference(fr: str, en: str) -> str | None:
    """Where two code cells differ beyond a translation.

    A translation may change comments and strings, and rename identifiers,
    as long as each fr name gets the same en name throughout the cell.

    Returns:
        The first difference, or None if there's none.
    """
    fr_tokens, en_tokens = code_tokens(fr), code_tokens(en)
    if fr_tokens is None or en_tokens is None:
        return None if fr == en else "code differs (doesn't tokenize)"
    if len(fr_tokens) != len(en_tokens):
        return f"code differs: {len(fr_tokens)} tokens in fr, {len(en_tokens)} in en"
    renames: dict[str, str] = {}
    for a, b in zip(fr_tokens, en_tokens, strict=True):
        if is_name(a) and is_name(b):
            if renames.setdefault(a, b) != b:
                return f"code differs: {a!r} is {renames[a]!r} and {b!r} in en"
        elif a.replace("_", "") != b.replace("_", ""):  # 29500 is 29_500
            return f"code differs: {a!r} in fr, {b!r} in en"
    return None


def pair_problems(fr: Path, en: Path) -> list[str]:
    """Structural differences between a notebook pair.

    Returns:
        One message per problem (cell count, cell types, code differing \
        beyond a translation).
    """
    fr_cells = json.loads(fr.read_text(encoding="utf-8"))["cells"]
    en_cells = json.loads(en.read_text(encoding="utf-8"))["cells"]
    problems = []
    if len(fr_cells) != len(en_cells):
        problems.append(f"{len(fr_cells)} cells in fr, {len(en_cells)} in en")
    for i, (a, b) in enumerate(zip(fr_cells, en_cells, strict=False)):
        if a["cell_type"] != b["cell_type"]:
            problems.append(f"[{i}] {a['cell_type']} in fr, {b['cell_type']} in en")
            break  # Past a shifted cell, every later comparison is noise.
        if a["cell_type"] == "code" and (
            difference := code_difference(cell_source(a), cell_source(b))
        ):
            problems.append(f"[{i}] {difference}")
    return problems


def compare_pairs(
    notebooks_dir: Path, lab_dirs: Sequence[Path] = ()
) -> Iterator[tuple[Path, list[str]]]:
    """Structural differences of every fr/en lab notebook pair.

    Args:
        notebooks_dir: Root directory the notebooks are found under.
        lab_dirs: Restrict to the pairs under one of these resolved, \
            absolute directories, or every pair if empty.

    Yields:
        `(stem, problems)` for every pair with at least one problem, `stem` \
        relative to `notebooks_dir`.
    """
    roots = lab_dirs or (notebooks_dir,)
    for stem, langs in variants(notebooks_dir).items():
        if set(LANGS) - langs or not any(stem.is_relative_to(root) for root in roots):
            continue
        fr, en = (stem.parent / f"{stem.name}-{lang}.ipynb" for lang in LANGS)
        if problems := pair_problems(fr, en):
            yield stem.relative_to(notebooks_dir), problems
