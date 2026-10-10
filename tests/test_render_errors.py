from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pytest import raises

from deckz.components.deck_builder import CopiedDependency, render_dependencies
from deckz.exceptions import RenderError


class _Renderer:
    """Renders with plain Jinja, as the repository's environment would."""

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **kwargs: Any
    ) -> None:
        env = Environment(
            loader=FileSystemLoader(template_path.parent), undefined=StrictUndefined
        )
        text = env.get_template(template_path.name).render(**kwargs)
        output_path.write_text(text, encoding="utf8")


class _Converter:
    def convert(self, source: Path, target: Path) -> None:
        target.write_text(source.read_text(encoding="utf8"), encoding="utf8")


def _render(tmp_path: Path, text: str) -> tuple[Path, Path]:
    source = tmp_path / "content" / "intro.md"
    source.parent.mkdir()
    source.write_text(text, encoding="utf8")
    copy = tmp_path / "build" / "intro.md.j2"
    copy.parent.mkdir()
    copy.write_text(text, encoding="utf8")
    render_dependencies(
        _Renderer(),  # ty: ignore[invalid-argument-type]
        _Converter(),  # ty: ignore[invalid-argument-type]
        [CopiedDependency(copy, {}, source)],
        ".typ",
    )
    return source, copy


def test_a_syntax_error_names_the_content_file_and_line(tmp_path: Path) -> None:
    with raises(RenderError) as error:
        _render(tmp_path, "# Title\n\nText\n{{ oops( }}\n")

    source = tmp_path / "content" / "intro.md"
    assert str(error.value).startswith(f"{source}:4: ")
    assert "expected" in str(error.value)
    # The next build renders it again, even with no change to the source.
    assert not (tmp_path / "build" / "intro.md.j2").exists()


def test_a_runtime_error_names_its_line_too(tmp_path: Path) -> None:
    with raises(RenderError) as error:
        _render(tmp_path, "# Title\n\n{{ variables.missing }}\n")

    source = tmp_path / "content" / "intro.md"
    assert str(error.value).startswith(f"{source}:3: ")
    assert "missing" in str(error.value)


def test_a_valid_file_renders(tmp_path: Path) -> None:
    _render(tmp_path, "# Title\n\n{{ 1 + 1 }}\n")

    assert (tmp_path / "build" / "intro.typ").read_text(encoding="utf8") == (
        "# Title\n\n2"
    )
