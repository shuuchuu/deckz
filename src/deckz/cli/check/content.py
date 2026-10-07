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
    carrying no stored outputs and demos carrying some (`lab-outputs`),
    asset credit lines free of LaTeX (`asset-credits`), and no raw LaTeX in
    content (`raw-latex`, `lab-urls`). A `templates/checks.py` module (see
    `GlobalPaths.checks_module`) can add the repository's own, merged in
    under their own names.

    With no CHECKS given, runs every one, deckz's built-ins first. Exits 1
    if any check reports a problem.

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
            one header per failing check
        json: Print the findings as one JSON object, instead
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit
    from sys import stderr

    from ...checking import export_staged
    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    if staged:
        exported = export_staged(settings.paths.git_dir)
        settings = GlobalSettings.from_yaml(exported, git_dir=exported)

    available = GlobalSettingsFactory(settings).checks_runner().checks()
    selected = checks if checks is not None else list(available)
    if unknown := [name for name in selected if name not in available]:
        print(f"unknown checks {unknown}: pick from {sorted(available)}", file=stderr)
        sys_exit(2)

    results = {name: problems for name in selected if (problems := available[name]())}

    if json:
        from .._presentation import print_json

        print_json(results)
    elif plain:
        for name, problems in results.items():
            for problem in problems:
                print(f"{name}\t{problem}")
    else:
        for name, problems in results.items():
            print(f"#### {name}", *(f"  {problem}" for problem in problems), sep="\n")

    if results:
        sys_exit(1)
