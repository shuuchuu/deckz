from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from cyclopts import Parameter

from . import app
from ._groups import EVERYDAY
from ._options import Langs, unique

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings
    from ..models import Lang


@app.command(group=EVERYDAY)
def upload(
    *,
    reserve: bool = False,
    links: Annotated[
        tuple[str, ...], Parameter(name="--link", negative="", show_default=False)
    ] = (),
    links_from: Annotated[Path | None, Parameter(name="--links")] = None,
    langs: Langs = ("fr",),
    include_stale: bool = False,
    skip_checks: bool = False,
    dry_run: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Upload pdfs, the slides' and the course notes', to Google Drive.

    Refuses when a PDF doesn't match the deck's content anymore (a fragment
    changed since it was built, its Drive links did, or no build produces
    it), naming them: a PDF a narrower build skipped (e.g. presentations
    after a handout-only build) would otherwise go online with old content.
    Refuses too while the content checks report a problem in the deck's
    files, deferred ones included (`deckz check`'s, which let a commit
    through but not the deck going out). Remote files with no local PDF of
    the same name are deleted (unless there's no local PDF at all), except
    the reserved ones.

    A deck with Drive links (see --reserve) shows them in its PDFs: each PDF
    goes to its reserved file, and the upload refuses a
    PDF with none (it would go out without its link), and a reserved PDF
    of the languages uploaded that isn't built (the others link to it).

    Args:
        reserve: Instead of uploading, create the Drive file of every PDF a
            full build of the deck writes in --lang (each kind, each part
            handout, the course notes in the languages they have chapters
            in) that has none yet, and record it in the deck's registry,
            yours (`drive-links/<deck path>.yml` in deckz's user config
            directory, every checkout's): the PDFs built afterwards show
            their links. A PDF already online keeps its link
        links: With --reserve, `<pdf>=<Drive link>` (repeatable): reserve
            that existing Drive file for the PDF (its path in the deck's
            directory, e.g. `pdf/<deck>-handout.pdf`) instead of a new one,
            to keep a link already handed out. The file stays where it is,
            with its name, shared read-only with anyone with its link; a file
            deckz didn't create is granted to it once, in Google's Picker,
            which opens in the browser
        links_from: With --reserve, a YAML file mapping PDFs of any decks
            (their paths in the repository) to their Drive links, as --link
            does for one deck: each deck it names gets its links reserved,
            those existing files with a single pass in the Picker for all of
            them. Run it from anywhere in the repository; run again after a
            failure, it picks up where it stopped
        langs: With --reserve, the languages to reserve links for
        include_stale: Upload the outdated PDFs too, those without a link,
            and without the reserved ones not built
        skip_checks: Don't run the content checks: upload whatever they
            would report
        dry_run: Only list the local PDFs it would upload, the outdated
            ones, those without a link, the reserved ones not built and the
            deck's problems, without connecting to Google Drive; with
            --reserve, the PDFs it would reserve a link for
        json: With --dry-run, print one JSON object (`pdfs`, `outdated`,
            `unlinked`, `unbuilt`: paths relative to the repository,
            `problems`: `<check>: <problem>`; with --reserve, `reserve`, and
            `link`: each --link PDF's file ID)
            instead
        workdir: Path to move into before running the command

    Raises:
        DeckzError: When a PDF is outdated, has no link, or a reserved one \
            isn't built, without --include-stale, or the checks report a \
            problem in the deck, without --skip-checks; when a --link is \
            malformed, names a PDF the deck doesn't build or one with \
            another link already, or its file isn't a PDF you can edit.
    """
    from .. import drive_links
    from ..analyzing.affected import deck_findings
    from ..components.factory import GlobalSettingsFactory
    from ..configuring.settings import DeckSettings
    from ..exceptions import DeckzError
    from ..extras import extras_imports
    from ..models import LANGS, lang_dir
    from ..pipelines import deck_targets, outdated_pdfs, published_targets

    if reserve:
        _reserve_requested(
            workdir, links, links_from, unique(langs), dry_run=dry_run, json=json
        )
        return
    if links or links_from is not None:
        msg = "--link and --links reserve Drive files: pass them with --reserve"
        raise DeckzError(msg)
    settings = DeckSettings.from_yaml(workdir)
    paths = settings.paths
    git_dir = paths.git_dir
    slides = {
        lang: sorted(lang_dir(paths.pdf_dir, lang).glob("*.pdf")) for lang in LANGS
    }
    uploaded = tuple(lang for lang in LANGS if slides[lang])
    notes = {
        lang: sorted(lang_dir(paths.course_notes_pdf_dir, lang).glob("*.pdf"))
        for lang in uploaded
    }
    pdfs = [pdf for lang in uploaded for pdf in (*slides[lang], *notes[lang])]
    outdated = (
        outdated_pdfs(
            published_targets(settings, uploaded)
            if any(notes.values())
            else deck_targets(settings, uploaded)
        )
        if dry_run or not include_stale
        else []
    )
    ids = drive_links.load(settings)
    unlinked = [pdf for pdf in pdfs if ids and pdf not in ids]
    lang_dirs = {
        lang_dir(directory, lang)
        for lang in uploaded
        for directory in (paths.pdf_dir, paths.course_notes_pdf_dir)
    }
    unbuilt = sorted(
        pdf for pdf in ids if pdf.parent in lang_dirs and not pdf.is_file()
    )
    problems = (
        []
        if skip_checks
        else [
            f"{finding.check}: {finding.text}"
            for finding in deck_findings(
                settings, GlobalSettingsFactory(settings).checks_runner().findings()
            )
        ]
    )
    if dry_run:
        found = {
            key: [str(pdf.relative_to(git_dir)) for pdf in listed]
            for key, listed in (
                ("pdfs", pdfs),
                ("outdated", outdated),
                ("unlinked", unlinked),
                ("unbuilt", unbuilt),
            )
        }
        _print_dry_run(found, problems, json=json)
        return
    refusals = []
    if outdated and not include_stale:
        refusals.append(
            f"these PDFs don't match the deck's content anymore:\n"
            f"{_listed(outdated, git_dir)}\n"
            "Rebuild them (`deckz run --all`, or `deckz run` with the kinds "
            "and languages they are, `--course-notes` for the course notes), "
            "delete them, or pass --include-stale to upload them as they are"
        )
    if unlinked and not include_stale:
        refusals.append(
            "these PDFs have no Drive link, which the deck's others show:\n"
            f"{_listed(unlinked, git_dir)}\n"
            "Reserve theirs (`deckz upload --reserve --lang ...`) and rebuild "
            "them, or pass --include-stale to upload them as they are"
        )
    if unbuilt and not include_stale:
        refusals.append(
            "these PDFs have a Drive link, which the deck's others may show, "
            f"but aren't built:\n{_listed(unbuilt, git_dir)}\n"
            "Build them (`deckz run --all`), or pass --include-stale to upload "
            "the others without them"
        )
    if problems:
        listed = "\n".join(f"  {problem}" for problem in problems)
        refusals.append(
            f"the content checks report problems in this deck's files:\n{listed}\n"
            "Fix them (each says how), or pass --skip-checks to upload the deck "
            "as it is"
        )
    if refusals:
        raise DeckzError("\n".join(refusals))

    with extras_imports():
        from ..extras.uploading import Uploader

    uploader = Uploader(settings)
    uploader.upload(pdfs, ids)
    print(f"Online folder: {uploader.folder_link}")


def _print_dry_run(
    found: dict[str, list[str]], problems: list[str], *, json: bool
) -> None:
    if json:
        from ._presentation import print_json

        print_json({**found, "problems": problems})
        return
    for pdf in found["pdfs"]:
        remarks = ", ".join(
            remark
            for remark, key in (("outdated", "outdated"), ("no link", "unlinked"))
            if pdf in found[key]
        )
        print(f"{pdf} ({remarks})" if remarks else pdf)
    for pdf in found["unbuilt"]:
        print(f"{pdf} (reserved, not built)")
    for problem in problems:
        print(f"problem: {problem}")


def _listed(pdfs: list[Path], git_dir: Path) -> str:
    return "\n".join(f"  {pdf.relative_to(git_dir)}" for pdf in pdfs)


def _reserve_requested(
    workdir: Path,
    links: tuple[str, ...],
    links_from: Path | None,
    langs: tuple["Lang", ...],
    *,
    dry_run: bool,
    json: bool,
) -> None:
    from .. import drive_links
    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..exceptions import DeckzError

    if links_from is None:
        decks = [(DeckSettings.from_yaml(workdir), list(links))]
    elif links:
        msg = "--link or --links, not both: put every link in the --links file"
        raise DeckzError(msg)
    else:
        git_dir = GlobalSettings.from_yaml(workdir).paths.git_dir
        decks = [
            (DeckSettings.from_yaml(deck_dir, git_dir=git_dir), requests)
            for deck_dir, requests in drive_links.links_file(
                links_from, git_dir
            ).items()
        ]
    _reserve(decks, langs, dry_run=dry_run, json=json)


def _reserve(
    decks: list[tuple["DeckSettings", list[str]]],
    langs: tuple["Lang", ...],
    *,
    dry_run: bool,
    json: bool,
) -> None:
    from .. import drive_links
    from ..extras import extras_imports
    from ..pipelines import published_pdfs, published_targets

    # Every request is checked, in every deck, before Drive is reached.
    plans = []
    for settings, requests in decks:
        ids = drive_links.load(settings)
        pdfs = published_pdfs(published_targets(settings, langs))
        adopted = drive_links.adoptions(settings, pdfs, requests)
        plans.append((settings, ids, adopted, [pdf for pdf in pdfs if pdf not in ids]))
    if dry_run:
        _print_reservations(plans, json=json)
        return
    if not any(missing for *_, missing in plans):
        print("Every PDF has its Drive link already")
        return
    with extras_imports():
        from ..extras.uploading import Uploader, adopt

    every_adopted = {
        pdf: id_ for _, _, adopted, _ in plans for pdf, id_ in adopted.items()
    }
    if every_adopted:
        adopt(plans[0][0], every_adopted)
    reserved = 0
    for settings, ids, adopted, missing in plans:
        if missing:
            uploader = Uploader(settings)
            drive_links.save(settings, uploader.reserve(missing, ids | adopted))
            reserved += len(missing)
    registries = (
        str(plans[0][0].paths.drive_links)
        if len(plans) == 1
        else f"the registries of {len(plans)} decks"
    )
    print(
        f"Reserved {reserved} Drive links in {registries}"
        + (f", {len(every_adopted)} of them existing files" if every_adopted else "")
        + ": rebuild the decks' PDFs to show them"
    )


def _print_reservations(
    plans: list[tuple["DeckSettings", dict[Path, str], dict[Path, str], list[Path]]],
    *,
    json: bool,
) -> None:
    found: list[str] = []
    given: dict[str, str] = {}
    for settings, _, adopted, missing in plans:
        git_dir = settings.paths.git_dir
        found.extend(str(pdf.relative_to(git_dir)) for pdf in missing)
        given |= {str(pdf.relative_to(git_dir)): id_ for pdf, id_ in adopted.items()}
    if json:
        from ._presentation import print_json

        print_json({"reserve": found, "link": given})
        return
    for pdf in found:
        print(f"{pdf} (link: {given[pdf]})" if pdf in given else pdf)
