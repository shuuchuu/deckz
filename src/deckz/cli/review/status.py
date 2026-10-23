from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...analyzing.review import FileReview, RankedSection, TargetReview


@app.command()
def status(
    targets: list[Path] | None = None,
    /,
    *,
    plain: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Show which files are reviewed at their current version, and which aren't.

    A file is fresh when its working-tree version is the one a report
    recorded (`deckz review mark`), stale when it changed since (with the
    lines added and removed), unreviewed when no report records it, deleted
    when a report records it and it's gone. A file several reports record
    takes the most recent mark.

    A TARGET that is a deck's directory lists its content files (in French,
    as `deckz show paths` resolves them) by section, then the other files
    (e.g. lab notebooks) the reports covering them record. Any other
    TARGET is a path: a content directory stands for the content files some
    deck includes under it (not their `en/` translations), another
    directory for its git-tracked files.

    With no TARGET, every shared section some deck uses, the most worth
    reviewing first: by the number of decks including one of its files
    times the frames of its stale and unreviewed files.

    Always exits 0: it only informs.

    Args:
        targets: Decks' directories or paths, from the current directory or
            the repository's root
        plain: Compact, stable lines for a script or an agent, their fields
            separated by tabs: per file, its state, path, `+<added>`,
            `-<removed>` (empty unless stale) and report (empty if none);
            per section, with no TARGET, its score, path, decks, fresh,
            stale and unreviewed files, and frames to review
        json: Print one JSON object instead: with no TARGET, `{"sections":
            [{section, decks, score, frames, fresh, stale, unreviewed,
            reports, files}]}`; else `{"targets": [{target, kind ("deck" or
            "paths"), sections: [{section, files}] and others (a deck), or
            files (paths)}]}`. A file is `{path, state, added, removed,
            frames, report, reports: [{report, date, base, blob}]}`, its
            reports the most recent mark first. Both have `problems`: the
            reports that couldn't be read
        workdir: Path to move into before running the command

    """
    from sys import stderr

    from ...analyzing.review import locate, review_status
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = review_status(settings, [locate(settings, t) for t in targets or ()])
    if json:
        from .._presentation import print_json

        if targets:
            print_json(
                {
                    "targets": [_target_json(t) for t in found.targets],
                    "problems": list(found.problems),
                }
            )
        else:
            print_json(
                {
                    "sections": [_ranked_json(r) for r in found.ranked],
                    "problems": list(found.problems),
                }
            )
        return
    if targets:
        for target in found.targets:
            _print_target(target, plain=plain)
    else:
        content = settings.paths.content_dir.relative_to(settings.paths.git_dir)
        _print_ranking(found.ranked, content.as_posix(), plain=plain)
    for problem in found.problems:
        print(f"unreadable report: {problem}", file=stderr)


def _file_json(review: "FileReview") -> dict[str, object]:
    return {
        "path": review.path,
        "state": review.state,
        "added": review.added,
        "removed": review.removed,
        "frames": review.frames,
        "report": review.report,
        "reports": [
            {
                "report": mark.report,
                "date": mark.date.isoformat(),
                "base": mark.base,
                "blob": mark.blob,
            }
            for mark in review.marks
        ],
    }


def _ranked_json(ranked: "RankedSection") -> dict[str, object]:
    return {
        "section": ranked.section,
        "decks": ranked.decks,
        "score": ranked.score,
        "frames": ranked.frames,
        "fresh": ranked.count("fresh"),
        "stale": ranked.count("stale"),
        "unreviewed": ranked.count("unreviewed"),
        "reports": list(ranked.reports),
        "files": [_file_json(review) for review in ranked.files],
    }


def _target_json(target: "TargetReview") -> dict[str, object]:
    if target.deck is None:
        return {
            "target": target.target,
            "kind": "paths",
            "files": [_file_json(r) for r in target.files],
        }
    return {
        "target": target.target,
        "kind": "deck",
        "sections": [
            {"section": s.section, "files": [_file_json(r) for r in s.files]}
            for s in target.deck.sections
        ],
        "others": [_file_json(r) for r in target.deck.others],
    }


def _state(review: "FileReview") -> str:
    if review.state != "stale":
        return review.state
    if review.added is None:
        return "stale (reviewed version not in this clone)"
    return f"stale +{review.added} -{review.removed}"


def _plain_line(review: "FileReview") -> str:
    added = "" if review.added is None else f"+{review.added}"
    removed = "" if review.removed is None else f"-{review.removed}"
    return "\t".join((review.state, review.path, added, removed, review.report or ""))


def _print_files(reviews: "Sequence[FileReview]", indent: str) -> None:
    width = max((len(_state(r)) for r in reviews), default=0)
    for review in reviews:
        where = f"  ({review.report})" if review.report else ""
        print(f"{indent}{_state(review):<{width}}  {review.path}{where}")


def _summary(reviews: "Sequence[FileReview]") -> str:
    counts = {
        state: sum(r.state == state for r in reviews)
        for state in ("fresh", "stale", "unreviewed", "deleted")
    }
    return ", ".join(f"{n} {state}" for state, n in counts.items() if n) or "no file"


def _print_target(target: "TargetReview", *, plain: bool) -> None:
    if target.deck is None:
        every = list(target.files)
        others: list[FileReview] = []
    else:
        every = [r for s in target.deck.sections for r in s.files]
        others = list(target.deck.others)
    if plain:
        for review in [*every, *others]:
            print(_plain_line(review))
        return
    if target.deck is None:
        print(f"{target.target}: {_summary(every)}")
        _print_files(every, "  ")
    else:
        print(f"{target.target}: {len(every)} content files, {_summary(every)}")
        for section in target.deck.sections:
            print(f"\n  {section.section}: {_summary(section.files)}")
            _print_files(section.files, "    ")
        if others:
            print(
                f"\n  Other files the reports covering them record: {_summary(others)}"
            )
            _print_files(others, "    ")
    reviews = [*every, *others]
    if any(r.state == "stale" for r in reviews):
        print("\nWhat changed since a review: `deckz review diff <report> [<path>...]`")
    if any(r.state == "deleted" for r in reviews):
        print("A deleted or renamed file: `deckz review mark <report> --forget <path>`")


def _print_ranking(
    ranked: "Sequence[RankedSection]", content: str, *, plain: bool
) -> None:
    if plain:
        for r in ranked:
            values = (
                r.score,
                r.section,
                r.decks,
                r.count("fresh"),
                r.count("stale"),
                r.count("unreviewed"),
                r.frames,
            )
            print("\t".join(str(value) for value in values))
        return
    if not ranked:
        print("No deck includes a shared section.")
        return
    width = max(len(r.section) for r in ranked)
    print(
        f"{'score':>6}  {'section':<{width}}  decks  fresh  stale  unreviewed  "
        "frames to review"
    )
    for r in ranked:
        print(
            f"{r.score:>6}  {r.section:<{width}}  {r.decks:>5}  "
            f"{r.count('fresh'):>5}  {r.count('stale'):>5}  "
            f"{r.count('unreviewed'):>10}  {r.frames:>16}"
        )
    print(
        "\nscore: the decks including the section times the frames of its stale "
        f"and unreviewed files. `deckz review status {content}/<section>` lists "
        "them, with its subsections'."
    )
