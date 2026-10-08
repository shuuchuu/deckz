from pathlib import Path

from . import app
from ._options import Langs, unique


@app.command()
def search_sections(
    keywords: list[str],
    /,
    *,
    langs: Langs = ("fr",),
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    r"""Search shared sections by keyword in yml titles and frame titles.

    Case-insensitive substring match, OR'd across KEYWORDS, against each
    section's title/default_titles (from its yml) and each of its own .md
    files' headings -- never against frame bodies, code or comments, so it
    does not false-positive on unrelated content that happens to mention a
    keyword.

    Searches each language in turn (English: the yml titles' `en` entries
    and the headings of en/ files), and prints one match per line:

    - `SECTION <lang> <section>\t<title>`: yml title/default_titles hit
    - `FRAME <lang> <section>\t<file>\t<frame_title>`: frame title hit

    `<section>` is a content-relative id (e.g. python/basics): check its
    yml for the flavor(s) that include `<file>` before referencing it.

    With --json, prints one JSON array of objects instead, each with a
    "kind" (section/frame), "lang", "section", "title" and, for a frame,
    "file".

    Args:
        keywords: Keywords to search for, matched with OR
        langs: Languages to search
        json: Print the matches as JSON
        workdir: Path to move into before running the command

    """
    from ..analyzing.sections_search import search_sections as compute
    from ..configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    results = [
        (lang, *compute(settings.paths.content_dir, keywords, lang))
        for lang in unique(langs)
    ]
    if json:
        from ._presentation import print_json

        print_json(
            [
                item
                for lang, section_matches, frame_matches in results
                for item in (
                    *(
                        {
                            "kind": "section",
                            "lang": lang,
                            "section": m.section,
                            "title": m.title,
                        }
                        for m in section_matches
                    ),
                    *(
                        {
                            "kind": "frame",
                            "lang": lang,
                            "section": m.section,
                            "file": m.file,
                            "title": m.frame_title,
                        }
                        for m in frame_matches
                    ),
                )
            ]
        )
        return
    for lang, section_matches, frame_matches in results:
        for section_match in section_matches:
            print(f"SECTION {lang} {section_match.section}\t{section_match.title}")
        for frame_match in frame_matches:
            print(
                f"FRAME {lang} {frame_match.section}\t{frame_match.file}\t"
                f"{frame_match.frame_title}"
            )
