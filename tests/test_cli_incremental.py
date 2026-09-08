import json
import sys  # noqa: F401
from pathlib import Path
from shutil import copytree, move
from typing import Any
from unittest.mock import patch

import appdirs
from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer
from pygit2 import init_repository
from pypdf import PdfReader
from pytest import fixture

from deckz.cli import main


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / __name__
    tmp_dir = tmp_path / "data"
    tmp_user_dir = tmp_path / "user"
    tmp_user_dir.mkdir()
    copytree(data_dir, tmp_dir)
    move(tmp_dir / "user-variables.yml", tmp_user_dir / "variables.yml")
    init_repository(str(tmp_dir))
    working_dir = tmp_dir / "company" / "abc"
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_dir))
    return working_dir


def extract_info(pdf_path: Path) -> tuple[int, str]:
    with pdf_path.open("rb") as fh:
        pages = list(extract_pages(fh))
        fh.seek(0)
        text = extract_text(fh)
    return len(pages), text


def run_deckz(*args: str) -> None:
    with patch("sys.argv", ["deckz", *args]):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise e


def _manifests(working_dir: Path) -> dict[Path, dict[str, Any]]:
    return {
        manifest_path: json.loads(manifest_path.read_text())
        for manifest_path in (working_dir / ".build").glob("*/fragments.json")
    }


def _page_texts(pdf_path: Path) -> list[str]:
    texts = []
    with pdf_path.open("rb") as fh:
        for page_layout in extract_pages(fh):
            parts = [
                element.get_text().strip()
                for element in page_layout
                if isinstance(element, LTTextContainer)
            ]
            texts.append(" | ".join(part for part in parts if part))
    return texts


def _flatten_outline(outline: list[Any]) -> list[Any]:
    flat = []
    for entry in outline:
        if isinstance(entry, list):
            flat.extend(_flatten_outline(entry))
        else:
            flat.append(entry)
    return flat


def test_run(working_dir: Path) -> None:
    run_deckz("run", "p1", "p2")

    n_pages, text = extract_info(working_dir / "pdf" / "abc-handout.pdf")
    assert "John Doe" in text
    assert n_pages > 0

    reader = PdfReader(working_dir / "pdf" / "abc-handout.pdf")
    outline_titles = {entry.title for entry in _flatten_outline(reader.outline)}
    # Section/subsection headings show up in the PDF outline, matching
    # hyperref's own bookmarks in legacy mode (unaffected by
    # subsectionstyle). Part dividers never do, in either mode: legacy has no
    # native way to track a manually-inserted [standout] frame, since it
    # isn't a LaTeX-level sectioning command either.
    assert {"First section", "Introduction", "Advanced", "Conclusion"} <= outline_titles
    assert "Part 1" not in outline_titles
    assert "Part 2" not in outline_titles

    # The printed ToC (unlike the outline) only lists sections, matching
    # legacy's \tableofcontents[subsectionstyle=hide]: no subsections, and no
    # part dividers either.
    toc_text = _page_texts(working_dir / "pdf" / "abc-handout.pdf")[1]
    assert "First section" in toc_text
    assert "Introduction" not in toc_text
    assert "Part 1" not in toc_text


def test_incremental_isolated_edit_recompiles_a_single_fragment(
    working_dir: Path,
) -> None:
    run_deckz("run", "p1", "p2")
    before = _manifests(working_dir)

    advanced = working_dir / "latex" / "first-section" / "advanced.tex"
    advanced.write_text(
        advanced.read_text().replace("Don't Panic.", "Don't Panic. Bring a towel.")
    )

    run_deckz("run", "p1", "p2")
    after = _manifests(working_dir)

    # Editing a single slide's text doesn't change its page/frame count, so it
    # shouldn't cascade into the skeleton (title page/ToC) at all.
    changed_relative_paths = set()
    for manifest_path, before_manifest in before.items():
        after_manifest = after[manifest_path]
        assert before_manifest["skeleton"] == after_manifest["skeleton"]
        for key, before_state in before_manifest["fragments"].items():
            after_state = after_manifest["fragments"][key]
            if before_state != after_state:
                changed_relative_paths.add(after_state["relative_path"])

    # "advanced" is a subsection of "First section", established by "intro"
    # (the first file of that section): recompiling "advanced" alone, without
    # "intro" having just issued \section{First section} in the same compile,
    # would leave a dangling \subsection with nothing to attach to. So "intro"
    # is necessarily pulled into the same batch too — but nothing beyond that,
    # since neither's own page/frame count changes.
    assert changed_relative_paths == {
        "latex/first-section/advanced",
        "latex/first-section/intro",
    }


def test_incremental_noop_rebuild_recompiles_nothing(working_dir: Path) -> None:
    run_deckz("run", "p1", "p2")
    before = _manifests(working_dir)

    run_deckz("run", "p1", "p2")
    after = _manifests(working_dir)

    assert before == after


def test_incremental_page_count_change_cascades_downstream(
    working_dir: Path,
) -> None:
    run_deckz("run", "p1", "p2")

    intro = working_dir / "latex" / "first-section" / "intro.tex"
    intro.write_text(
        intro.read_text()
        + "\n\\begin{frame}\n  \\frametitle{More}\n  More.\n\\end{frame}\n"
    )

    run_deckz("run", "p1", "p2")

    _, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert "More." in text

    reader = PdfReader(working_dir / "pdf" / "abc-p1-presentation.pdf")
    outline_pages = [
        reader.get_destination_page_number(entry)
        for entry in _flatten_outline(reader.outline)
    ]
    assert outline_pages == sorted(outline_pages)

    # The edit cascades into every fragment after it in this item, since their
    # printed page/frame numbers all shift — but they should have been batched
    # into a single compile job (one shared PDF) rather than recompiled one at a
    # time, which is the whole point of batching.
    manifest = json.loads(
        (working_dir / ".build" / "abc-p1-presentation" / "fragments.json").read_text()
    )
    pdf_files = {state["pdf_file"] for state in manifest["fragments"].values()}
    assert len(manifest["fragments"]) > len(pdf_files)


def test_incremental_batched_fragments_do_not_repeat_section_dividers(
    working_dir: Path,
) -> None:
    # A cold build stales every fragment of an item at once, so p1's fragments
    # (2 flavors of "first-section", 3 and 2 files respectively) all land in a
    # single batch. Each batch member replays its own breadcrumb of active
    # section/subsection titles, and with metropolis' sectionpage=progressbar
    # (used by the fixture template), replaying an *unchanged* section title
    # would incorrectly insert an extra divider frame for it before every
    # file, instead of only where that section actually starts.
    run_deckz("run", "p1", "p2")

    texts = _page_texts(working_dir / "pdf" / "abc-p1-presentation.pdf")
    bare_section_dividers = [text for text in texts if text == "First section"]
    # "First section" is used as two separate flavors in p1's deck.yml, each a
    # distinct occurrence of the section and thus legitimately showing its own
    # bare divider frame — but no more than that.
    assert len(bare_section_dividers) == 2


def test_incremental_toc_links_do_not_accumulate_across_runs(
    working_dir: Path,
) -> None:
    run_deckz("run", "p1", "p2")
    manifest = json.loads(
        (working_dir / ".build" / "abc-handout" / "fragments.json").read_text()
    )
    toc_page_index = manifest["skeleton"]["physical_page_count"] - 1

    def toc_annotation_count() -> int:
        reader = PdfReader(working_dir / "pdf" / "abc-handout.pdf")
        annots = reader.pages[toc_page_index].get("/Annots")
        return len(annots.get_object()) if annots else 0

    before_count = toc_annotation_count()
    assert before_count > 0

    # Edit a fragment that doesn't affect abc-handout's skeleton (title page/
    # ToC) at all: the skeleton is re-sourced as-is from the previous output
    # instead of being recompiled (see _old_page_starts), which used to leave
    # the ToC page's stale link annotations in place for _add_toc_links to
    # then pile a fresh set on top of.
    advanced = working_dir / "latex" / "first-section" / "advanced.tex"
    advanced.write_text(
        advanced.read_text().replace("Don't Panic.", "Don't Panic. Bring a towel.")
    )
    run_deckz("run", "p1", "p2")

    assert toc_annotation_count() == before_count


def test_incremental_two_edits_with_untouched_gap_stay_consistent(
    working_dir: Path,
) -> None:
    # Edit "advanced" (p1/first-section/standard) and "about" (p2) in the same
    # run. In abc-handout's whole-deck timeline these land in two separate
    # batches (advanced pulls in "intro" for context, "about" is self-
    # contained as the first fragment of its own part), with several
    # untouched items in between: first-section/standard's "conclusion", both
    # files of the "light" flavor, and the Part 2 divider. Assembling the
    # final PDF must correctly interleave the two freshly-compiled batches
    # with that untouched middle stretch (re-sourced from the previous
    # output, see _old_page_starts) without dropping, duplicating, or
    # misplacing any of it.
    run_deckz("run", "p1", "p2")
    n_pages_before, _ = extract_info(working_dir / "pdf" / "abc-handout.pdf")

    advanced = working_dir / "latex" / "first-section" / "advanced.tex"
    advanced.write_text(
        advanced.read_text().replace("Don't Panic.", "Don't Panic. Bring a towel.")
    )
    about = working_dir / "latex" / "about.tex"
    about.write_text(about.read_text().replace("Your speaker", "Your speaker EDITED"))

    run_deckz("run", "p1", "p2")

    manifest = json.loads(
        (working_dir / ".build" / "abc-handout" / "fragments.json").read_text()
    )
    advanced_pdf = manifest["fragments"][
        next(
            key
            for key, state in manifest["fragments"].items()
            if state["relative_path"] == "latex/first-section/advanced"
        )
    ]["pdf_file"]
    about_pdf = manifest["fragments"][
        next(
            key
            for key, state in manifest["fragments"].items()
            if state["relative_path"] == "latex/about"
        )
    ]["pdf_file"]
    assert advanced_pdf != about_pdf

    n_pages_after, text = extract_info(working_dir / "pdf" / "abc-handout.pdf")
    assert n_pages_after == n_pages_before
    assert "Bring a towel" in text
    assert "EDITED" in text
    # Content untouched by either edit, on both sides of and in between the
    # two batches, must still be present and intact.
    assert "Would it save you a lot of time" in text  # intro (before both)
    assert "The ships hung in the sky" in text  # conclusion (in the gap)

    reader = PdfReader(working_dir / "pdf" / "abc-handout.pdf")
    outline_pages = [
        reader.get_destination_page_number(entry)
        for entry in _flatten_outline(reader.outline)
    ]
    assert outline_pages == sorted(outline_pages)


def test_legacy_mode_still_renders_title_page_and_toc(working_dir: Path) -> None:
    # The template has to serve both renderers correctly, but nothing else in
    # this file exercises the non-incremental one: a template change that
    # gates \maketitle or the ToC content behind a variable only the
    # incremental renderer passes (e.g. is_skeleton, toc_entries) would
    # silently break legacy mode while every other test here keeps passing.
    deckz_yml = working_dir.parent.parent / "deckz.yml"
    deckz_yml.write_text(
        deckz_yml.read_text().replace(
            "incremental_compilation: true", "incremental_compilation: false"
        )
    )

    run_deckz("run", "p1", "p2")

    texts = _page_texts(working_dir / "pdf" / "abc-handout.pdf")
    assert "John Doe" in texts[0]
    assert "First section" in texts[1]
