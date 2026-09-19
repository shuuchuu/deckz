#!/usr/bin/env python3
"""Migrate a deckz-managed repo off separate English decks/sections.

This is a one-shot, re-runnable tool for a *deckz-managed repo* (not this
`deckz` codebase itself) that still uses the old bilingual convention:

- a full sibling `<deck>/en/deck.yml` (with its own `<deck>/en/latex/` and
  optional `<deck>/en/variables.yml`) for every translated deck;
- a sibling `<section>/en/en.yml` re-declaring the *same* flavor structure as
  `<section>/<section>.yml` for every translated shared section, with
  translated body files already conventionally at `<section>/en/<file>`.

It rewrites the repo onto the new, single-source-of-truth convention deckz
now understands:

- one `deck.yml`/`<section>.yml` per deck/section, merging every fr/en title
  pair that actually differs into a `{fr: ..., en: ...}` translation map. A
  title that has no en counterpart to merge with is left as a plain string --
  that's a valid, permanent state (it just means "the same in every
  language"), not something this script needs to paper over;
- translated body files staying/moving to `<parent-dir>/en/<filename>`, for
  *every* file location uniformly (this already matches today's shared-section
  convention; only deck-local files, which today live under a wholly separate
  `<deck>/en/latex/` tree, need to move).

Usage:

    python scripts/migrate_en_decks.py REPO_PATH [--apply] [--git-mv] [--only PATH ...]

Dry-run by default (reports what it would do); pass --apply to actually touch
the filesystem. Exits non-zero if any deck/section had a FATAL structural
parity issue between its fr and en sides (skipped entirely, no writes) -- run
it again after resolving those by hand.

Known limitations (see the plan / final report for specifics):

- Structural parity between an fr/en pair is checked by comparing normalized
  `(path, flavor)` include keys as multisets; when the *same* key appears more
  than once in a list, fr and en occurrences are paired positionally, in
  order of appearance -- correct for the common case, best-effort otherwise.
- Only deck-level variables.yml vs en/variables.yml are merged (no sibling en
  tree exists above deck level today).
"""

from __future__ import annotations

import shutil
import subprocess
from argparse import ArgumentParser
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from posixpath import normpath as posix_normpath
from typing import Any

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.indent(mapping=2, sequence=4, offset=2)


def load_raw(path: Path) -> Any:
    with path.open(encoding="utf8") as fh:
        return _yaml.load(fh)


def dump_raw(data: Any, path: Path) -> None:
    with path.open("w", encoding="utf8") as fh:
        _yaml.dump(data, fh)


########################################################################################
# Discovery                                                                            #
########################################################################################


def _has_en_segment(path: Path, root: Path) -> bool:
    return "en" in path.relative_to(root).parts[:-1]


def discover_deck_ymls(repo: Path) -> list[Path]:
    """Every fr deck.yml in the repo (i.e. not itself an `en/deck.yml`)."""
    return sorted(p for p in repo.rglob("deck.yml") if not _has_en_segment(p, repo))


def discover_section_ymls(shared_latex_dir: Path) -> list[Path]:
    """Every canonical fr shared-section yml (i.e. not an `en/en.yml`)."""
    return sorted(
        p
        for p in shared_latex_dir.rglob("*.yml")
        if p.parent.name == p.stem and not _has_en_segment(p, shared_latex_dir)
    )


########################################################################################
# Normalization / parity checking (ported from the retired i18n_analyzer.py)           #
########################################################################################


def _normalized_parts(path_part: str, anchor: str) -> list[str]:
    resolved = path_part if path_part.startswith("/") else f"{anchor}/{path_part}"
    return [p for p in posix_normpath(resolved).split("/") if p and p != "en"]


def _include_key(item: Any) -> str:
    return item if isinstance(item, str) else next(iter(item))


def _raw_title(item: Any) -> Any | None:
    if isinstance(item, str):
        return None
    (title,) = item.values()
    return title


def _normalize_include(item: Any, anchor: str) -> str:
    key = _include_key(item)
    if key.startswith("$"):
        path_part, _, flavor_part = key[1:].partition("@")
        parts = _normalized_parts(path_part, anchor)
        name = parts[-1] if parts else path_part
        return f"section:{name}@{flavor_part}"
    return "file:" + "/".join(_normalized_parts(key, anchor))


def check_deck_parity(fr_data: Any, en_data: Any) -> list[str]:
    """Structural fr/en parity issues for a deck pair; empty if clean."""
    issues: list[str] = []
    fr_parts = {p["name"]: p for p in fr_data.get("parts") or ()}
    en_parts = {p["name"]: p for p in en_data.get("parts") or ()}
    if set(fr_parts) != set(en_parts):
        issues.append(
            f"part names differ: fr-only={sorted(set(fr_parts) - set(en_parts))} "
            f"en-only={sorted(set(en_parts) - set(fr_parts))}"
        )
        return issues
    for name, fr_part in fr_parts.items():
        en_part = en_parts[name]
        fr_c = Counter(_normalize_include(i, "") for i in fr_part.get("sections") or ())
        en_c = Counter(_normalize_include(i, "") for i in en_part.get("sections") or ())
        if fr_c != en_c:
            issues.append(
                f"part {name!r}: fr-only={dict(fr_c - en_c)} en-only={dict(en_c - fr_c)}"
            )
    return issues


def check_section_parity(fr_data: Any, en_data: Any, section_id: str) -> list[str]:
    """Structural fr/en parity issues for a shared-section pair; empty if clean."""
    issues: list[str] = []
    fr_flavors = {f["name"]: f for f in fr_data.get("flavors") or ()}
    en_flavors = {f["name"]: f for f in en_data.get("flavors") or ()}
    if set(fr_flavors) != set(en_flavors):
        issues.append(
            f"flavor names differ: fr-only={sorted(set(fr_flavors) - set(en_flavors))} "
            f"en-only={sorted(set(en_flavors) - set(fr_flavors))}"
        )
        return issues
    for name, fr_flavor in fr_flavors.items():
        en_flavor = en_flavors[name]
        fr_c = Counter(
            _normalize_include(i, section_id) for i in fr_flavor.get("includes") or ()
        )
        en_c = Counter(
            _normalize_include(i, f"{section_id}/en")
            for i in en_flavor.get("includes") or ()
        )
        if fr_c != en_c:
            issues.append(
                f"flavor {name!r}: fr-only={dict(fr_c - en_c)} "
                f"en-only={dict(en_c - fr_c)}"
            )
    return issues


########################################################################################
# Title merging                                                                        #
########################################################################################


def merged_title(fr_title: Any, en_title: Any) -> dict[str, Any] | None:
    """The new fr-side title value to write, or None if nothing should change."""
    if en_title is None or fr_title is None:
        return None
    if isinstance(fr_title, dict) or isinstance(en_title, dict):
        return None  # already (partially) bilingual -- don't guess, leave alone
    if fr_title == en_title:
        return None
    return {"fr": fr_title, "en": en_title}


def _merge_include_titles(
    fr_items: list[Any], en_items: list[Any], anchor_fr: str, anchor_en: str
) -> None:
    en_pool: dict[str, list[int]] = {}
    for i, item in enumerate(en_items):
        en_pool.setdefault(_normalize_include(item, anchor_en), []).append(i)
    for i, item in enumerate(fr_items):
        pool = en_pool.get(_normalize_include(item, anchor_fr))
        if not pool:
            continue
        en_item = en_items[pool.pop(0)]
        merged = merged_title(_raw_title(item), _raw_title(en_item))
        if merged is not None:
            fr_items[i] = {_include_key(item): merged}


def merge_deck_titles(fr_data: Any, en_data: Any) -> None:
    en_parts = {p["name"]: p for p in en_data.get("parts") or ()}
    for fr_part in fr_data.get("parts") or ():
        en_part = en_parts.get(fr_part["name"])
        if en_part is None:
            continue
        merged = merged_title(fr_part.get("title"), en_part.get("title"))
        if merged is not None:
            fr_part["title"] = merged
        _merge_include_titles(
            fr_part.get("sections") or [], en_part.get("sections") or [], "", "en"
        )


def merge_section_titles(fr_data: Any, en_data: Any, section_id: str) -> None:
    merged = merged_title(fr_data.get("title"), en_data.get("title"))
    if merged is not None:
        fr_data["title"] = merged

    fr_dt = fr_data.get("default_titles") or {}
    en_dt = en_data.get("default_titles") or {}
    for key, en_title in en_dt.items():
        merged = merged_title(fr_dt.get(key), en_title)
        if merged is not None:
            fr_dt[key] = merged

    en_flavors = {f["name"]: f for f in en_data.get("flavors") or ()}
    for fr_flavor in fr_data.get("flavors") or ():
        en_flavor = en_flavors.get(fr_flavor["name"])
        if en_flavor is None:
            continue
        merged = merged_title(fr_flavor.get("title"), en_flavor.get("title"))
        if merged is not None:
            fr_flavor["title"] = merged
        _merge_include_titles(
            fr_flavor.get("includes") or [],
            en_flavor.get("includes") or [],
            section_id,
            f"{section_id}/en",
        )


########################################################################################
# Variables merging                                                                    #
########################################################################################


def merge_variables(fr_path: Path, en_path: Path, *, apply: bool) -> list[str]:
    """Merge en/variables.yml into fr's variables.yml; returns FATAL messages."""
    if not en_path.is_file():
        return []
    fr_data = load_raw(fr_path) if fr_path.is_file() else {}
    en_data = load_raw(en_path) or {}
    issues = []
    changed = False
    for key, en_value in en_data.items():
        if key not in fr_data:
            issues.append(f"{en_path}: key {key!r} only in en, not in {fr_path}")
            continue
        merged = merged_title(fr_data[key], en_value)
        if merged is not None:
            fr_data[key] = merged
            changed = True
    if changed and apply:
        dump_raw(fr_data, fr_path)
    return issues


########################################################################################
# Local content migration                                                              #
########################################################################################


def _move(src: Path, dst: Path, *, use_git_mv: bool, cwd: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if use_git_mv:
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=cwd, check=True)
    else:
        shutil.move(str(src), str(dst))


def _local_section_en_counterpart(
    fr_yml: Path, en_latex_dir: Path, local_latex_dir: Path
) -> Path | None:
    """The mirrored en counterpart of a local section's own yml, if any.

    A deck-local section that was translated only inside the old separate
    `en/latex` tree (never in-place next to the fr yml) shows up there in one
    of two shapes: sibling-style (`<rel>/en/en.yml`, matching the shared-
    section convention) or duplicate-style (`<rel>/<name>.yml`, a fully
    independent copy referenced by the *same* unprefixed `$name@flavor`, since
    the old en-deck's own separate local_latex_dir made that resolve to its
    own copy without needing an "/en" suffix anywhere).
    """
    rel_dir = fr_yml.parent.relative_to(local_latex_dir)
    for candidate in (
        en_latex_dir / rel_dir / "en" / "en.yml",
        en_latex_dir / rel_dir / fr_yml.name,
    ):
        if candidate.is_file():
            return candidate
    return None


def migrate_local_sections(
    deck_dir: Path, report: Report, *, apply: bool
) -> set[Path]:
    """Merge deck-local section pairs; returns the en ymls consumed this way.

    Mirrors `migrate_sections`, but scoped to a deck's own local latex tree
    -- a local override of a shared section can be translated the exact same
    way a shared section is, in-place (`<section>/en/en.yml`) or, in a
    deck that predates this script, only inside the separate `en/latex` tree
    (see `_local_section_en_counterpart`).
    """
    local_latex_dir = deck_dir / "latex"
    en_latex_dir = deck_dir / "en" / "latex"
    consumed: set[Path] = set()
    for fr_yml in discover_section_ymls(local_latex_dir):
        section_id = fr_yml.parent.relative_to(local_latex_dir).as_posix()
        in_place_en_yml = fr_yml.parent / "en" / "en.yml"
        en_yml = (
            in_place_en_yml
            if in_place_en_yml.is_file()
            else _local_section_en_counterpart(fr_yml, en_latex_dir, local_latex_dir)
        )
        if en_yml is None:
            continue
        fr_data = load_raw(fr_yml)
        en_data = load_raw(en_yml)
        issues = check_section_parity(fr_data, en_data, section_id)
        if issues:
            report.fatal.append((fr_yml, issues))
            continue
        merge_section_titles(fr_data, en_data, section_id)
        report.migrated_sections.append(fr_yml)
        consumed.add(en_yml)
        if apply:
            dump_raw(fr_data, fr_yml)
            if en_yml.is_relative_to(en_latex_dir):
                en_yml.unlink()
    return consumed


def relocate_local_en_files(
    deck_dir: Path, consumed: set[Path], *, apply: bool, use_git_mv: bool
) -> list[tuple[Path, Path]]:
    """Move whatever's left of `<deck>/en/latex/**` into `<deck>/latex/`.

    A file whose path already ends in `.../en/<filename>` (e.g. a shared- or
    local-section-style translated body already living in an in-tree `en/`
    sibling of the old separate en-deck) is mirrored verbatim -- inserting
    *another* "en" segment would double it up. Only a genuinely unprefixed
    path (the common case for deck-root files, which the old convention
    relied on the separate `en/latex` root itself to make "English", with no
    "en" segment anywhere in the include path) gets one inserted.
    """
    en_latex_dir = deck_dir / "en" / "latex"
    local_latex_dir = deck_dir / "latex"
    moves = []
    if not en_latex_dir.is_dir():
        return moves
    for src in sorted(p for p in en_latex_dir.rglob("*") if p.is_file()):
        if src in consumed:
            continue
        rel = src.relative_to(en_latex_dir)
        dst = (
            local_latex_dir / rel
            if rel.parent.name == "en"
            else local_latex_dir / rel.parent / "en" / rel.name
        )
        moves.append((src, dst))
        if apply:
            _move(src, dst, use_git_mv=use_git_mv, cwd=deck_dir)
    return moves


########################################################################################
# Cleanup                                                                              #
########################################################################################


def _remove_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), reverse=True):
        if child.is_dir():
            _remove_empty_dirs(child)
    with suppress(OSError):
        root.rmdir()


########################################################################################
# Orchestration                                                                        #
########################################################################################


@dataclass
class Report:
    migrated_decks: list[Path] = field(default_factory=list)
    migrated_sections: list[Path] = field(default_factory=list)
    moved_files: list[tuple[Path, Path]] = field(default_factory=list)
    variable_issues: list[str] = field(default_factory=list)
    fatal: list[tuple[Path, list[str]]] = field(default_factory=list)

    def render(self) -> str:
        lines = []
        if self.migrated_decks:
            lines.append("Merged fr/en titles for decks:")
            lines.extend(f"  {p}" for p in self.migrated_decks)
        if self.migrated_sections:
            lines.append("Merged fr/en titles for sections:")
            lines.extend(f"  {p}" for p in self.migrated_sections)
        if self.moved_files:
            lines.append("Moved deck-local en/ files:")
            lines.extend(f"  {src} -> {dst}" for src, dst in self.moved_files)
        if self.variable_issues:
            lines.append("Variable merge issues (FATAL, needs manual review):")
            lines.extend(f"  {msg}" for msg in self.variable_issues)
        if self.fatal:
            lines.append("FATAL parity issues (skipped entirely, no writes):")
            for path, issues in self.fatal:
                lines.append(f"  {path}:")
                lines.extend(f"    {issue}" for issue in issues)
        if not lines:
            lines.append("Nothing to migrate.")
        return "\n".join(lines)


def migrate_decks(
    repo: Path, only: list[Path] | None, *, apply: bool, git_mv: bool
) -> Report:
    report = Report()
    for fr_path in discover_deck_ymls(repo):
        deck_dir = fr_path.parent
        if only and not any(deck_dir.is_relative_to(o) for o in only):
            continue
        en_path = deck_dir / "en" / "deck.yml"
        if not en_path.is_file():
            continue
        fr_data = load_raw(fr_path)
        en_data = load_raw(en_path)
        issues = check_deck_parity(fr_data, en_data)
        if issues:
            report.fatal.append((fr_path, issues))
            continue
        merge_deck_titles(fr_data, en_data)
        report.migrated_decks.append(fr_path)

        consumed = migrate_local_sections(deck_dir, report, apply=apply)
        moves = relocate_local_en_files(
            deck_dir, consumed, apply=apply, use_git_mv=git_mv
        )
        report.moved_files.extend(moves)

        en_vars = deck_dir / "en" / "variables.yml"
        fr_vars = deck_dir / "variables.yml"
        report.variable_issues.extend(merge_variables(fr_vars, en_vars, apply=apply))

        if apply:
            dump_raw(fr_data, fr_path)
            en_path.unlink()
            if en_vars.is_file():
                en_vars.unlink()
            _remove_empty_dirs(deck_dir / "en")
    return report


def migrate_sections(shared_latex_dir: Path, report: Report, *, apply: bool) -> None:
    for fr_path in discover_section_ymls(shared_latex_dir):
        section_dir = fr_path.parent
        section_id = section_dir.relative_to(shared_latex_dir).as_posix()
        en_path = section_dir / "en" / "en.yml"
        if not en_path.is_file():
            continue
        fr_data = load_raw(fr_path)
        en_data = load_raw(en_path)
        issues = check_section_parity(fr_data, en_data, section_id)
        if issues:
            report.fatal.append((fr_path, issues))
            continue
        merge_section_titles(fr_data, en_data, section_id)
        report.migrated_sections.append(fr_path)

        if apply:
            dump_raw(fr_data, fr_path)
            en_path.unlink()


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("repo_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--git-mv", action="store_true")
    parser.add_argument("--only", type=Path, nargs="*", default=None)
    args = parser.parse_args()

    repo = args.repo_path.resolve()
    only = [(repo / o).resolve() for o in args.only] if args.only else None

    report = migrate_decks(repo, only, apply=args.apply, git_mv=args.git_mv)
    migrate_sections(repo / "shared" / "latex", report, apply=args.apply)

    print(report.render())
    if not args.apply:
        print("\n(dry run -- pass --apply to write changes)")
    if report.fatal:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
