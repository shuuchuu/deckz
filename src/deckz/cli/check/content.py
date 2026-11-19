from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from cyclopts import Parameter

from . import app

if TYPE_CHECKING:
    from ...configuring.settings import GlobalSettings


@app.command(name="content")
@app.default
def content(
    checks: list[str] | None = None,
    /,
    *,
    file: Annotated[
        tuple[Path, ...], Parameter(consume_multiple=True, negative="")
    ] = (),
    staged: bool = False,
    timings: bool = False,
    plain: bool = False,
    json: bool = False,
    baseline: Path | None = None,
    workdir: Path = Path(),
) -> None:
    """Run deckz's generic content checks, plus the target repo's own plugin ones.

    Deckz's own checks need no repository-specific setup: lab notebook IDs
    (`lab-ids`), fr/en lab notebook pairs (`lab-pairs`), hands-on notebooks
    carrying no stored outputs and demos with code carrying some
    (`lab-outputs`), nothing credential-like in a notebook (`lab-secrets`),
    notebooks in deckz's canonical JSON (`lab-format`),
    asset credit lines free of LaTeX (`asset-credits`), no raw LaTeX in
    content (`raw-latex`), no hand-written link to the published notebooks
    or a lab's repository (`lab-urls`), content files' Jinja tags
    (`jinja-syntax`), every deck parsing in French (`deck-definitions`),
    with `review.dir`, review reports' front matter well formed and
    naming existing files (`review-headers`), course notes chapters
    writing out a content file (`course-notes-files`) and existing in fr
    and en (`course-notes-pairs`), and their Python code printing what they
    show (`course-notes-code`, opt-in: it runs the code, see
    `course_notes.code` in `deckz.yml`).
    A `templates/checks.py` module (see `GlobalPaths.checks_module`) can
    add the repository's own, merged in under their own names.

    With no CHECKS given, runs every one, deckz's built-ins first, except
    the opt-in ones (`course-notes-code`, and those `checks.opt_in`
    lists), which run only when named, and exits 1 if a blocking check reports a
    problem. A deferred
    check's problems (`checks.deferred`; by default every built-in but
    `lab-secrets`, `jinja-syntax`, `deck-definitions` and `review-headers`)
    are printed
    without failing: their harm comes later than the commit (a lab
    published, a deck uploaded), and `deckz status` keeps showing them.
    Checks named in CHECKS fail on any problem.

    Args:
        checks: Only run these checks, by name, instead of every one
        file: Limit the checks that read files to these ones (`--file a.md
            b.md`), e.g. `deckz check course-notes-code --file
            supports/x.md` to run one chapter's code; the other checks
            still read the whole repository
        staged: Check the git index's staged version of every tracked
            file, exported to a scratch directory, instead of the working
            tree: other sessions' unfinished edits neither block this nor
            hide a problem that would otherwise be committed. A check
            needing the repository's git history or remotes (e.g.
            `lab-urls`) does nothing under `--staged`, since the export has
            no `.git` of its own. Unless checks are named, the blocking
            checks then read the whole export, but the deferred ones only
            the staged files, and their problems are only counted: the
            rest of their backlog isn't the commit's (`deckz status` lists
            it). Those of `checks.not_after_edit`, whose verdict depends on
            other files, don't run. A check of `checks.staged_triggers`
            runs, unless named, only when a staged change matches one of
            its patterns
        timings: Also print what each check cost, slowest first: its CPU
            time (deckz's and its subprocesses') and its wall-clock time.
            The checks then all run one after the other, none in a thread
            (`checks.in_thread`), so that each one's CPU time is its own;
            the process pool parsing the decks for several checks gets a row
            of its own, `(shared process pool)`
        plain: Compact, stable lines for a script or an agent, instead of
            one header per failing check: `blocking` or `deferred`, the
            check's name and the problem, separated by tabs
        json: Print the findings as one JSON object, instead: `blocking`
            and `deferred`, each mapping a check's name to its problems
        baseline: Report only the problems this file doesn't list (the
            `--plain` lines of an earlier run, e.g. last night's), then
            rewrite it with every problem found, for the next run: a
            backlog fails the run, and is printed, once, and a problem
            fixed then back is new again. No file yet: every problem is new.
            The scheduled CI checks use it (`deckz hooks install --ci`), so
            their issue gets what changed rather than the same list every
            night; `deckz check` without it still lists them all
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit
    from sys import stderr

    from ...checking import export_staged, staged_changes
    from ...components.checks import CheckTiming, run_checks
    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from .._presentation import print_checks

    settings = GlobalSettings.from_yaml(workdir)
    paths = [(workdir / path).resolve() for path in file] or None
    changed = None
    if staged:
        git_dir = settings.paths.git_dir.resolve()
        changed = staged_changes(git_dir)
        exported = export_staged(settings.paths.git_dir)
        settings = GlobalSettings.from_yaml(exported, git_dir=exported)
        if paths is not None:
            paths = [exported / path.relative_to(git_dir) for path in paths]

    available = GlobalSettingsFactory(settings).checks_runner().checks()
    selected = (
        checks
        if checks is not None
        else [name for name in available if settings.checks.runs_unnamed(name)]
    )
    if unknown := [name for name in selected if name not in available]:
        print(f"unknown checks {unknown}: pick from {sorted(available)}", file=stderr)
        sys_exit(2)
    jobs: dict[str, Collection[Path] | None] = dict.fromkeys(selected, paths)
    if checks is None and changed is not None:
        jobs = _staged_jobs(settings, jobs, changed)

    costs: dict[str, CheckTiming] | None = {} if timings else None
    results = {
        name: problems
        for name, problems in run_checks(
            available, jobs, in_thread=settings.checks.in_thread, timings=costs
        ).items()
        if problems
    }
    blocking = {
        name: problems
        for name, problems in results.items()
        if checks is not None or settings.checks.blocking(name)
    }
    deferred = {
        name: problems for name, problems in results.items() if name not in blocking
    }
    if baseline is not None:
        blocking, deferred = _new_since(baseline, blocking, deferred)

    print_checks(
        blocking,
        deferred,
        plain=plain,
        json=json,
        count_deferred=staged,
        timings=costs,
    )
    if blocking:
        sys_exit(1)


type _Found = dict[str, list[str]]


def _new_since(
    baseline: Path, blocking: _Found, deferred: _Found
) -> tuple[_Found, _Found]:
    # `--baseline`: what `baseline` doesn't list, then all of it written there.
    from logging import getLogger

    from .._presentation import plain_check_line, plain_check_lines

    known = (
        set(baseline.read_text(encoding="utf-8").splitlines())
        if baseline.is_file()
        else set()
    )

    def new(found: _Found, level: str) -> _Found:
        kept = {
            name: [
                problem
                for problem in problems
                if plain_check_line(level, name, problem) not in known
            ]
            for name, problems in found.items()
        }
        return {name: problems for name, problems in kept.items() if problems}

    new_blocking, new_deferred = new(blocking, "blocking"), new(deferred, "deferred")
    lines = plain_check_lines(blocking, deferred)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    if repeated := len(lines) - len(plain_check_lines(new_blocking, new_deferred)):
        getLogger(__name__).info(
            f"{repeated} problem{'s' if repeated > 1 else ''} already in {baseline},"
            " not repeated (`deckz check` without --baseline lists them)"
        )
    return new_blocking, new_deferred


def _staged_jobs(
    settings: "GlobalSettings",
    jobs: dict[str, Collection[Path] | None],
    changed: Collection[str],
) -> dict[str, Collection[Path] | None]:
    # `deckz check --staged` run unnamed: a check of `staged_triggers` only for
    # the changes that decide it; a deferred one on the staged files alone
    # (their problems are only counted), unless its verdict depends on others.
    from logging import getLogger

    logger = getLogger(__name__)
    checks = settings.checks
    # `settings` are the export's (`export_staged`).
    staged_paths = [settings.paths.git_dir / path for path in changed]
    found: dict[str, Collection[Path] | None] = {}
    left_out = []
    for name, paths in jobs.items():
        if not checks.runs_on_staged(name, changed):
            patterns = ", ".join(checks.staged_triggers[name])
            logger.info(
                f"{name} not run: no staged change matches its "
                f"checks.staged_triggers ({patterns})"
            )
        elif checks.blocking(name) or paths is not None:
            found[name] = paths
        elif name in checks.not_after_edit:
            left_out.append(name)
        else:
            found[name] = staged_paths
    if left_out:
        logger.info(
            f"{', '.join(left_out)} not run on a commit (checks.not_after_edit: "
            "their verdict depends on files the commit doesn't change; `deckz "
            "status` runs them)"
        )
    return found
