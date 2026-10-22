from pathlib import Path

from . import app


@app.command()
def repos(*names: str, fetch: bool = True, workdir: Path = Path()) -> None:
    """Report how the labs with their own repository drift from their notebooks.

    Fetches each repository `labs.repos` declares (into a mirror under the git
    directory), then reports a branch missing, undeclared, or lacking commits of
    the one it stacks on, a README that doesn't give the statement yet, a lab with
    no hands-on notebook in a start branch's language, and a README whose Colab
    links name no notebook's ID or not its own; as notes, a README last changed
    before its notebook, with the notebook's commits since. Exits 1 on a problem.

    Args:
        names: Repositories to report on (`owner/name`, or `name`), all by default
        fetch: Fetch the repositories first (`--no-fetch`: the last fetched state)
        workdir: Path to move into before running the command

    """
    from sys import exit as sys_exit

    from ...configuring.settings import GlobalSettings
    from ...labs.repos import report

    settings = GlobalSettings.from_yaml(workdir)
    declared = settings.labs.repos
    chosen = [
        repo
        for repo in declared
        if not names or repo.repo in names or repo.repo.split("/")[-1] in names
    ]
    if unknown := sorted(
        set(names) - {n for r in declared for n in (r.repo, r.repo.split("/")[-1])}
    ):
        print(f"not in labs.repos: {', '.join(unknown)}")
        sys_exit(2)
    failed = False
    for repo in chosen:
        found = report(settings, repo, fetch=fetch)
        print(f"{repo.repo} ({repo.lab})")
        for problem in found.problems:
            print(f"  {problem}")
        for note in found.notes:
            print("  note: " + note.replace("\n", "\n  "))
        if not found.problems and not found.notes:
            print("  ok")
        failed = failed or bool(found.problems)
    if failed:
        sys_exit(1)
