from pathlib import Path
from sys import executable

from . import app


@app.command()
def check(
    notebooks: list[Path],
    /,
    *,
    smoke: bool = False,
    python: str = executable,
    container: bool = False,
    timeout: int = 300,
    deprecations: bool = False,
    workdir: Path = Path(),
) -> None:
    """Structural checks and an execution of every notebook's code cells.

    Structural: a solution heading not collapsed in Colab, an empty
    solution section, a stored error output. Execution: every code cell of
    NOTEBOOKS (a file, or a directory searched recursively for `*.ipynb`)
    runs in order, in a throwaway directory, reporting which cells raise.
    It mirrors Colab's shell lines and magics, but runs only harmless data
    fetches among the shell commands; `--container` runs everything, in the
    published repository's dev container (what Codespaces opens, built from
    `labs/published/.devcontainer/`; needs Docker). A shell command that
    fails (`!cmd`, `%pip`) doesn't raise, as in Colab, where the cell goes
    on: each one gets its own line, `[i] shell command exited with code N:
    cmd`, before the verdict on raising cells. So does each deprecation a
    cell's own code meets (`[i] DeprecationWarning: …`, or
    `PendingDeprecationWarning`, `FutureWarning`: the warning points at the
    cell), once per place, which a library's next release may turn into an
    error (not reported with `--container`): a warning, listed apart at the
    end, unless `--deprecations` counts it as a problem. With `ci.labs` set
    in `deckz.yml`, the scheduled CI job runs it with `--deprecations` on
    those notebooks every Sunday (`deckz hooks install --ci`).

    With `--container`, a notebook's run needs (`labs.run.metadata_key`:
    variables and secrets from the environment or `.env`, a hook of
    `labs.run.hooks` run before and after) are filled in the copy that runs,
    and a secret's value is redacted from every line; one that isn't set
    leaves the notebook as a trainee runs it, with a line saying so, which
    isn't a problem.

    Args:
        notebooks: Notebook files, or directories to search recursively
            for notebook files
        smoke: Cap every Lightning Trainer (1 epoch, a few batches) so a
            CPU run finishes
        python: Interpreter to run the cells with, e.g. a throwaway venv
            with the labs' libraries installed (this process's own may not
            have them); a relative path is from the current directory
        container: Run each notebook for real in the published
            repository's dev container, under its published name, instead
            of with PYTHON
        timeout: Seconds bounding the whole notebook's execution
        deprecations: Count the deprecations the cells meet as problems,
            failing the check, instead of warnings
        workdir: Path to move into before running the command

    Raises:
        DeckzError: If PYTHON, a path, names no file.
        SystemExit: With code 1 when a notebook has a problem: a structural
            one, a cell that raises, a shell command that fails, a timeout
            or a crash (or, with --deprecations, a deprecation).

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.container import dev_container
    from ...labs.execution import check_notebook, is_deprecation, is_problem
    from ...labs.notebook import notebook_paths
    from ...labs.publishing import notebook_id, repository_name

    settings = GlobalSettings.from_yaml(workdir)
    if "/" in python:
        # The runner starts in a throwaway directory: a relative path would
        # be read from there.
        python = str(Path(python).absolute())
        if not container and not Path(python).is_file():
            from ...exceptions import DeckzError

            msg = (
                f"--python {python}: no such interpreter; give the labs' "
                "environment's (e.g. `uv venv <dir>`, then `<dir>/bin/python`)"
            )
            raise DeckzError(msg)
    dev = (
        dev_container(
            settings.paths.labs_published_dir,
            repository_name(
                settings.paths.git_dir,
                settings.labs.published_files_remote or settings.labs.publish_remote,
            ),
        )
        if container
        else None
    )
    failed = []
    warned = []
    for path in notebook_paths(notebooks):
        print(f"#### {path}")
        lab_id = notebook_id(path, settings.labs.id_metadata_key)
        for line in check_notebook(
            path,
            heading=settings.labs.solution_heading,
            python=python,
            smoke=smoke,
            timeout=timeout,
            container=dev,
            name=f"{lab_id}.ipynb" if lab_id else None,
            run_settings=settings.labs.run,
            hooks_cwd=settings.paths.git_dir,
        ):
            print(line)
            if is_problem(line, deprecations=deprecations):
                if not failed or failed[-1] != path:
                    failed.append(path)
            elif is_deprecation(line) and (not warned or warned[-1] != path):
                warned.append(path)
        print()
    if warned:
        print(
            f"{len(warned)} notebook(s) meeting deprecations, warnings only "
            "(--deprecations counts them as problems):"
        )
        print("\n".join(f"  {path}" for path in warned))
    if failed:
        print(f"{len(failed)} notebook(s) with problems:")
        print("\n".join(f"  {path}" for path in failed))
        raise SystemExit(1)
