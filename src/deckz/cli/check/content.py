from pathlib import Path

from . import app


@app.command(name="content")
@app.default
def content(
    checks: list[str] | None = None,
    /,
    *,
    staged: bool = False,
    plain: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Run deckz's generic content checks, plus the target repo's own plugin ones.

    Deckz's own checks need no repository-specific setup: lab notebook IDs
    (`lab-ids`), fr/en lab notebook pairs (`lab-pairs`), hands-on notebooks
    carrying no stored outputs and demos with code carrying some
    (`lab-outputs`), nothing credential-like in a notebook (`lab-secrets`),
    notebooks in deckz's canonical JSON (`lab-format`),
    asset credit lines free of LaTeX (`asset-credits`), no raw LaTeX in
    content (`raw-latex`, `lab-urls`), content files' Jinja tags
    (`jinja-syntax`), and every deck parsing in French (`deck-definitions`).
    A `templates/checks.py` module (see `GlobalPaths.checks_module`) can
    add the repository's own, merged in under their own names.

    With no CHECKS given, runs every one, deckz's built-ins first, except
    those `deckz.yml` lists under `checks.opt_in`, which run only when
    named, and exits 1 if a blocking check reports a problem. A deferred
    check's problems (`checks.deferred`; by default every built-in but
    `lab-secrets`, `jinja-syntax` and `deck-definitions`) are printed
    without failing: their harm comes later than the commit (a lab
    published, a deck uploaded), and `deckz status` keeps showing them.
    Checks named in CHECKS fail on any problem.

    Args:
        checks: Only run these checks, by name, instead of every one
        staged: Check the git index's staged version of every tracked
            file, exported to a scratch directory, instead of the working
            tree: other sessions' unfinished edits neither block this nor
            hide a problem that would otherwise be committed. A check
            needing the repository's git history or remotes (e.g.
            `lab-urls`) does nothing under `--staged`, since the export has
            no `.git` of its own
        plain: Compact, stable lines for a script or an agent, instead of
            one header per failing check: `blocking` or `deferred`, the
            check's name and the problem, separated by tabs
        json: Print the findings as one JSON object, instead: `blocking`
            and `deferred`, each mapping a check's name to its problems
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit
    from sys import stderr

    from ...checking import export_staged
    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from .._presentation import print_checks

    settings = GlobalSettings.from_yaml(workdir)
    if staged:
        exported = export_staged(settings.paths.git_dir)
        settings = GlobalSettings.from_yaml(exported, git_dir=exported)

    available = GlobalSettingsFactory(settings).checks_runner().checks()
    selected = (
        checks
        if checks is not None
        else [name for name in available if name not in settings.checks.opt_in]
    )
    if unknown := [name for name in selected if name not in available]:
        print(f"unknown checks {unknown}: pick from {sorted(available)}", file=stderr)
        sys_exit(2)

    results = {name: problems for name in selected if (problems := available[name]())}
    blocking = {
        name: problems
        for name, problems in results.items()
        if checks is not None or settings.checks.blocking(name)
    }
    deferred = {
        name: problems for name, problems in results.items() if name not in blocking
    }

    print_checks(blocking, deferred, plain=plain, json=json)
    if blocking:
        sys_exit(1)
