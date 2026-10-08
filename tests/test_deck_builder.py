"""DeckBuilder's orchestration, with fake renderer, converter and compiler.

No pandoc or Typst needed: the fakes only record calls and write files.
"""

from collections.abc import Mapping
from pathlib import Path, PurePath
from signal import SIGINT, pthread_kill
from threading import Event, get_ident
from time import sleep
from typing import Any

from pytest import MonkeyPatch, raises

from deckz.components import deck_builder
from deckz.components.deck_builder import DeckBuilder, Format, OutputFormat
from deckz.components.progress import NullProgress
from deckz.models import (
    CompileResult,
    Deck,
    File,
    Part,
    PartName,
    ResolvedDeck,
    ResolvedPath,
    UnresolvedPath,
)


class FakeRenderer:
    def __init__(self) -> None:
        self.fragments: list[Path] = []

    def render_to_str(self, template_path: Path, /, **_: Any) -> tuple[str, Any]:
        return template_path.read_text(encoding="utf8"), {}

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **kwargs: Any
    ) -> Any:
        if template_path.suffix == ".j2":
            self.fragments.append(template_path)
        text = template_path.read_text(encoding="utf8")
        if template_path.suffix == ".html":
            # An HTML main template inlines its fragments.
            text += "".join(
                kwargs["fragment"](section)
                for part in kwargs["parts"]
                for section in part.sections
                if isinstance(section, str)
            )
        output_path.write_text(f"{text}{kwargs.get('variables', {})}", encoding="utf8")
        return {}

    def environment_for(self, suffix: str) -> Any:
        raise NotImplementedError


class FakeConverter:
    def __init__(self) -> None:
        self.version = "1"
        self.converted: list[Path] = []

    def convert(self, source: Path, destination: Path) -> None:
        self.converted.append(source)
        destination.write_text(source.read_text(encoding="utf8"), encoding="utf8")

    def fingerprint(self) -> str:
        return self.version


class FakeCompiler:
    def __init__(self) -> None:
        self.ok = True

    def compile(self, file: Path) -> CompileResult:
        if not self.ok:
            return CompileResult(ok=False, diagnostics="boom")
        file.with_suffix(".pdf").write_bytes(b"%PDF")
        return CompileResult(ok=True)


class FakePackager:
    def compile(self, file: Path) -> CompileResult:
        site = file.with_suffix(".site")
        site.mkdir(exist_ok=True)
        (site / "index.html").write_text(file.read_text(encoding="utf8"))
        return CompileResult(ok=True)


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.content = root / "content"
        self.content.mkdir()
        self.template = root / "main.typ"
        self.template.write_text("main", encoding="utf8")
        self.html_template = root / "main.html"
        self.html_template.write_text("<main>", encoding="utf8")
        self.renderer = FakeRenderer()
        self.converter = FakeConverter()
        self.html_converter = FakeConverter()
        self.compiler = FakeCompiler()
        self.packager = FakePackager()

    def write(self, name: str, text: str) -> None:
        (self.content / name).write_text(text, encoding="utf8")

    def file(self, name: str, variables: Mapping[str, Any] | None = None) -> File:
        return File(
            title=None,
            unresolved_path=UnresolvedPath(PurePath(name).with_suffix("")),
            resolved_path=ResolvedPath(self.content / name),
            parsing_error=None,
            variables=variables or {},
        )

    def builder(
        self,
        *files: File,
        handout: bool = True,
        html: bool = False,
        part_handouts: bool = True,
    ) -> DeckBuilder:
        deck = Deck(name="deck", parts={PartName("p1"): Part(title=None, nodes=files)})
        return DeckBuilder(
            variables={},
            deck=ResolvedDeck(deck),
            build_presentation=False,
            build_handout=handout,
            build_print=False,
            build_html=html,
            formats={
                Format.Typst: OutputFormat(
                    template=self.template,
                    fragment_suffix=".typ",
                    markdown_converter=self.converter,
                    compiler=self.compiler,
                    output_dir=self.root / "pdf",
                    artifact_suffix=".pdf",
                    output_suffix=".pdf",
                ),
                Format.Html: OutputFormat(
                    template=self.html_template,
                    fragment_suffix=".html",
                    markdown_converter=self.html_converter,
                    compiler=self.packager,
                    output_dir=self.root / "html",
                    artifact_suffix=".site",
                    output_suffix="",
                ),
            },
            build_dir=self.root / "build",
            dirs_to_link=(),
            basedirs=(self.content,),
            renderer=self.renderer,
            progress=NullProgress(),
            build_part_handouts=part_handouts,
        )


def _repo(tmp_path: Path) -> Repo:
    repo = Repo(tmp_path)
    repo.write("a.md", "A")
    repo.write("b.md", "B")
    return repo


def test_build_renders_converts_and_publishes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert repo.builder(repo.file("a.md"), repo.file("b.md")).build_deck()

    assert sorted(p.name for p in (tmp_path / "pdf").iterdir()) == [
        "deck-handout.pdf",
        "deck-p1-handout.pdf",
    ]
    # Two PDFs, each with its own build dir and so its own two fragments.
    assert len(repo.renderer.fragments) == 4
    assert len(repo.converter.converted) == 4


def test_build_without_part_handouts_only_publishes_the_whole_deck(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    builder = repo.builder(repo.file("a.md"), part_handouts=False)

    assert builder.output_paths() == [tmp_path / "pdf" / "deck-handout.pdf"]
    assert builder.build_deck()
    assert [p.name for p in (tmp_path / "pdf").iterdir()] == ["deck-handout.pdf"]


def test_failed_compile_publishes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.compiler.ok = False

    assert not repo.builder(repo.file("a.md")).build_deck()

    assert not (tmp_path / "pdf").exists()


def test_rebuild_only_renders_changed_fragments(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    files = (repo.file("a.md"), repo.file("b.md"))
    repo.builder(*files).build_deck()
    repo.renderer.fragments.clear()

    repo.write("a.md", "A, edited")
    builder = repo.builder(*files)
    planned = builder.plan()
    builder.build_deck()

    assert [(p.full_render, p.changed_fragments) for p in planned] == [
        (False, (repo.content / "a.md",))
    ] * 2
    # a.md re-rendered once per PDF, b.md not at all.
    assert len(repo.renderer.fragments) == 2
    assert all(p.name.startswith("a-") for p in repo.renderer.fragments)


def test_converter_change_renders_everything(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    files = (repo.file("a.md"), repo.file("b.md"))
    repo.builder(*files).build_deck()
    repo.renderer.fragments.clear()

    repo.converter.version = "2"
    builder = repo.builder(*files)
    planned = builder.plan()
    builder.build_deck()

    assert all(p.full_render for p in planned)
    assert len(repo.renderer.fragments) == 4


def test_same_file_with_different_variables_renders_twice(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    repo.builder(
        repo.file("a.md", {"depth": "shallow"}), repo.file("a.md", {"depth": "deep"})
    ).build_deck()

    rendered = sorted(
        path.read_text(encoding="utf8")
        for path in (tmp_path / "build" / "deck-handout").glob("a-*.md")
    )
    assert rendered == ["A{'depth': 'deep'}", "A{'depth': 'shallow'}"]


def test_html_inlines_converted_fragments_and_publishes_a_directory(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    builder = repo.builder(
        repo.file("a.md"), repo.file("b.md"), handout=False, html=True
    )
    planned = builder.plan()
    assert builder.build_deck()

    assert [p.output_path for p in planned] == [tmp_path / "html" / "deck-html"]
    build_dir = tmp_path / "build" / "deck-html"
    assert len(list(build_dir.glob("*.html"))) == 3  # the page, two fragments
    assert not list(build_dir.glob("*.typ"))
    assert repo.html_converter.converted
    assert not repo.converter.converted
    index = (tmp_path / "html" / "deck-html" / "index.html").read_text(encoding="utf8")
    # The main template was rendered after the fragments it inlines.
    assert index.startswith("<main>")
    assert "A{}" in index
    assert "B{}" in index


def test_html_publishing_removes_stale_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.builder(repo.file("a.md"), handout=False, html=True).build_deck()
    stale = tmp_path / "html" / "deck-html" / "img" / "old.png"
    stale.parent.mkdir()
    stale.write_bytes(b"")

    repo.builder(repo.file("a.md"), handout=False, html=True).build_deck()

    assert not stale.parent.exists()
    assert (tmp_path / "html" / "deck-html" / "index.html").is_file()


def test_html_without_its_format_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    deck = Deck(name="deck", parts={PartName("p1"): Part(title=None, nodes=())})

    with raises(ValueError, match="html"):
        DeckBuilder(
            variables={},
            deck=ResolvedDeck(deck),
            build_presentation=False,
            build_handout=False,
            build_print=False,
            build_html=True,
            formats={},
            build_dir=tmp_path / "build",
            dirs_to_link=(),
            basedirs=(repo.content,),
            renderer=repo.renderer,
            progress=NullProgress(),
        )


def test_interrupt_does_not_wait_for_running_compilations(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    compiled: list[Path] = []
    main_thread = get_ident()
    release = Event()
    finished = Event()

    def ctrl_c_during_compilation(file: Path) -> CompileResult:
        # Ctrl-C reaches the main thread while this compilation still runs,
        # the part's PDF still queued behind it.
        compiled.append(file)
        pthread_kill(main_thread, SIGINT)
        release.wait(timeout=10)
        finished.set()
        return CompileResult(ok=True)

    monkeypatch.setattr(repo.compiler, "compile", ctrl_c_during_compilation)
    # One thread, so that the part's PDF waits in the queue.
    monkeypatch.setattr(deck_builder, "cpu_count", lambda: 1)

    with raises(KeyboardInterrupt):
        repo.builder(repo.file("a.md")).build_deck()

    # Raised without waiting for the running compilation, which the CLI then
    # stops, and without starting the queued one.
    assert not finished.is_set()
    release.set()
    sleep(0.5)
    assert len(compiled) == 1
