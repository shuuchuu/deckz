import json
from pathlib import Path

from . import app


@app.command()
def dump(notebooks: list[Path], /, *, workdir: Path = Path()) -> None:
    """Print a compact, readable view of one or more notebooks.

    Cells numbered, solution cells marked, stored outputs summarized.

    Args:
        notebooks: Notebook files, or directories to search recursively
            for notebook files
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.inspecting import dump_lines
    from ...labs.notebook import notebook_paths

    settings = GlobalSettings.from_yaml(workdir)
    for path in notebook_paths(notebooks):
        notebook = json.loads(path.read_text(encoding="utf-8"))
        print(f"#### {path}")
        for line in dump_lines(notebook, heading=settings.labs.solution_heading):
            print(line)
        print()
