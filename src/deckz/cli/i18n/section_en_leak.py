from pathlib import Path

from . import app


@app.command()
def section_en_leak(section: str, /, *, workdir: Path = Path()) -> None:
    """Flag any file an en section flavor resolves to that isn't itself under en/.

    Complementary to section-flavor-diff -- run both together, never this \
    alone. Resolves every flavor declared in <SECTION>/en/en.yml with deckz's \
    own engine and flags any resolved file that does not sit under an "en" \
    path segment, with no exceptions. This catches drift section-flavor-diff \
    is structurally blind to: an absolute include that forgot its "/en" \
    suffix (e.g. "$/python/databases@light" instead of "$/python/databases/en\
    @light") normalizes to the same key on both sides, so the structural diff \
    sees a match while deckz silently resolves to the French shared file.

    Prints one finding per line, nothing if clean:

    - NO_EN_YML <path>: nothing to check yet
    - FLAVOR <name> LEAK <path>: resolved file outside any en/ dir
    - FLAVOR <name> ERROR <message>: flavor failed to resolve (e.g. a \
        referenced subsection has no en/ yet -- a prerequisite, not a leak)

    Args:
        section: Shared/latex-relative section id, e.g. python/basics
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_analyzer import section_en_leak as compute
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    for finding in compute(
        settings.paths.shared_latex_dir, settings.file_extensions, section
    ):
        print(finding)
