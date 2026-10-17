from pathlib import Path

from . import app


@app.command(name="list")
def list_labs(*, json: bool = False, workdir: Path = Path()) -> None:
    """List every lab notebook: its lab, its kind and its language.

    One line per notebook (`<lab>/<kind>-<lang>.ipynb` under the configured
    notebooks directory): its lab's directory, relative to that directory,
    its kind (`demo`, `hands-on`…) and its language. `deckz labs missing`
    lists the notebooks a lab lacks in the other language.

    Args:
        json: Print one JSON object instead: `notebooks_dir`, and
            `notebooks`, each with its `lab`, `kind`, `language` and `file`;
            paths relative to the repository
        workdir: Path to move into before running the command

    """
    import json as json_module

    from ...configuring.settings import GlobalSettings
    from ...labs.comparison import variants

    settings = GlobalSettings.from_yaml(workdir)
    git_dir = settings.paths.git_dir
    notebooks_dir = settings.paths.labs_notebooks_dir
    labs = variants(notebooks_dir) if notebooks_dir.is_dir() else {}
    found = [
        (stem, lang)
        for stem, langs in labs.items()
        for lang in sorted(langs, key=lambda lang: (lang != "fr", lang))
    ]
    if not json:
        for stem, lang in found:
            lab = stem.parent.relative_to(notebooks_dir).as_posix()
            print(f"{lab}\t{stem.name}\t{lang}")
        return
    print(
        json_module.dumps(
            {
                "notebooks_dir": notebooks_dir.relative_to(git_dir).as_posix(),
                "notebooks": [
                    {
                        "lab": stem.parent.relative_to(notebooks_dir).as_posix(),
                        "kind": stem.name,
                        "language": lang,
                        "file": (stem.parent / f"{stem.name}-{lang}.ipynb")
                        .relative_to(git_dir)
                        .as_posix(),
                    }
                    for stem, lang in found
                ],
            },
            indent=2,
        )
    )
