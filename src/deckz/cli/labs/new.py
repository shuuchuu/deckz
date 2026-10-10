from pathlib import Path

from . import app


@app.command()
def new(lab: str, kind: str, /, *, workdir: Path = Path()) -> None:
    """Create the fr and en notebooks of the lab LAB, of KIND hands-on or demo.

    LAB is its path under the notebooks directory, e.g.
    `nn/cnn/image-segmentation-keras`. Both notebooks start from the
    repository's `templates/scaffold/lab/<kind>.ipynb`, else a minimal one,
    in deckz's format, and get their published IDs. Refuses if one exists.

    Args:
        lab: The lab's path under the notebooks directory
        kind: `hands-on` or `demo`
        workdir: Path to move into before running the command
    """
    from ...configuring.settings import GlobalSettings
    from ...scaffolding import new_lab

    settings = GlobalSettings.from_yaml(workdir)
    created = new_lab(settings, lab, kind)
    for path in created.paths:
        print(path.relative_to(settings.paths.git_dir))
    if created.ids:
        print("IDs:", ", ".join(created.ids))
    if snippet := settings.labs.link_snippet:
        print("Link it from a content file with:")
        print("  " + snippet.replace("{lab}", lab).replace("{kind}", kind))
