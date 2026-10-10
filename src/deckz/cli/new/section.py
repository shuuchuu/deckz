from pathlib import Path

from . import app


@app.command()
def section(
    section: str, /, *, title: str | None = None, workdir: Path = Path()
) -> None:
    """Create the shared section SECTION, e.g. `nlp/search`.

    Writes its `.yml` (a `full` flavor including one file), that file and
    its `en/` twin, each holding one frame titled TITLE. Lists the existing
    sections whose titles share a word with it first: one may already cover
    the subject. Refuses if the section exists.

    Args:
        section: The section's path under the shared content directory
        title: Its title (both languages until translated), from its name
            by default
        workdir: Path to move into before running the command
    """
    from ...analyzing.sections_search import search_sections
    from ...configuring.settings import GlobalSettings
    from ...scaffolding import new_section

    settings = GlobalSettings.from_yaml(workdir)
    keywords = [
        word
        for word in [*section.replace("/", "-").split("-"), *(title or "").split()]
        if len(word) > 3
    ]
    if keywords:
        titles, frames = search_sections(settings.paths.content_dir, keywords)
        close = sorted({match.section for match in [*titles, *frames]})
        if close:
            print("Existing sections sharing a word with it:", ", ".join(close[:10]))
    for path in new_section(settings, section, title):
        print(path.relative_to(settings.paths.git_dir))
