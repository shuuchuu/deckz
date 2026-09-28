"""DeckBuilder's orchestration, with fake renderer, converter and compiler.

No pandoc or Typst needed: the fakes only record calls and write files.
"""

from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Any

from pytest import MonkeyPatch, raises

from deckz.components import deck_builder
from deckz.components.deck_builder import DeckBuilder
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
        variables = kwargs.get("variables", {})
        output_path.write_text(
            f"{template_path.read_text(encoding='utf8')}{variables}", encoding="utf8"
        )
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


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.content = root / "content"
        self.content.mkdir()
        self.template = root / "main.typ"
        self.template.write_text("main", encoding="utf8")
        self.renderer = FakeRenderer()
        self.converter = FakeConverter()
        self.compiler = FakeCompiler()

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

    def builder(self, *files: File) -> DeckBuilder:
        deck = Deck(name="deck", parts={PartName("p1"): Part(title=None, nodes=files)})
        return DeckBuilder(
            variables={},
            deck=ResolvedDeck(deck),
            build_presentation=False,
            build_handout=True,
            build_print=False,
            output_dir=self.root / "pdf",
            build_dir=self.root / "build",
            dirs_to_link=(),
            template=self.template,
            basedirs=(self.content,),
            compiler=self.compiler,
            renderer=self.renderer,
            markdown_converter=self.converter,
            progress=NullProgress(),
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


def test_interrupt_cancels_the_queued_compilations(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    compiled: list[Path] = []

    def interrupted(file: Path) -> CompileResult:
        compiled.append(file)
        raise KeyboardInterrupt

    monkeypatch.setattr(repo.compiler, "compile", interrupted)
    # One thread: the part's PDF is still queued when the deck's is interrupted.
    monkeypatch.setattr(deck_builder, "cpu_count", lambda: 1)

    with raises(KeyboardInterrupt):
        repo.builder(repo.file("a.md")).build_deck()

    assert len(compiled) == 1
