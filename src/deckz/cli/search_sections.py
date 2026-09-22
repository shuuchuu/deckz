from pathlib import Path

from . import app


@app.command()
def search_sections(keywords: list[str], /, *, workdir: Path = Path()) -> None:
    r"""Search shared sections by keyword in yml titles and frame titles.

    Case-insensitive substring match, OR'd across KEYWORDS, against each \
    section's title/default_titles (from its yml) and each of its own .tex \
    files' frame titles (\begin{frame}{...}) -- never against frame bodies, \
    code or comments, so it does not false-positive on unrelated content that \
    happens to mention a keyword.

    Prints one match per line:

    - SECTION <section>\t<title>: yml title/default_titles hit
    - FRAME <section>\t<file>\t<frame_title>: frame title hit

    <section> is a latex-relative id (e.g. python/basics): check its \
    yml for the flavor(s) that include <file> before referencing it.

    Args:
        keywords: Keywords to search for, matched with OR
        workdir: Path to move into before running the command

    """
    from ..analyzing.sections_search import search_sections as compute
    from ..configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    section_matches, frame_matches = compute(settings.paths.latex_dir, keywords)
    for section_match in section_matches:
        print(f"SECTION {section_match.section}\t{section_match.title}")
    for frame_match in frame_matches:
        print(
            f"FRAME {frame_match.section}\t{frame_match.file}\t"
            f"{frame_match.frame_title}"
        )
