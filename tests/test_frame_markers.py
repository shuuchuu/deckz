from pathlib import Path

from pytest import raises

from deckz.components.frame_markers import (
    FrameMarkingConverter,
    frame_headings,
    mark_frames,
)
from deckz.exceptions import DeckzError

_TEXT = """# First {.standout}

```python
# not a frame
```

~~~~
```
# not one either
~~~~

## A subsection, not a frame

# Second
"""


def test_frame_headings_skips_code_blocks_and_lower_levels() -> None:
    assert frame_headings(_TEXT) == [(0, "First {.standout}"), (13, "Second")]


def test_mark_frames_adds_one_marker_after_each_frame_heading() -> None:
    marked = mark_frames(_TEXT, "/build/x-0123456789abcdef.md")

    lines = marked.splitlines()
    first = lines.index("# First {.standout}")
    assert lines[first + 2] == "```{=typst}"
    assert lines[first + 3] == (
        '#context [#metadata((fragment: "/build/x-0123456789abcdef.md", index: 0, '
        "page: here().page())) <deckz-frame>]"
    )
    assert "index: 1," in lines[lines.index("# Second") + 3]
    assert marked.count("<deckz-frame>") == 2
    # Nothing else changes.
    assert frame_headings(marked) == [
        (first, "First {.standout}"),
        (lines.index("# Second"), "Second"),
    ]


class _Recording:
    def __init__(self, fail: bool = False) -> None:
        self.converted: list[str] = []
        self._fail = fail

    def convert(self, source: Path, destination: Path) -> None:
        self.converted.append(source.read_text(encoding="utf8"))
        if self._fail:
            msg = f"pandoc failed to convert {source}"
            raise DeckzError(msg)
        destination.write_text("converted", encoding="utf8")

    def fingerprint(self) -> str:
        return "inner"


def test_converter_converts_a_marked_copy_and_leaves_the_fragment(
    tmp_path: Path,
) -> None:
    fragment = tmp_path / "frag.md"
    fragment.write_text("# Title\n", encoding="utf8")
    inner = _Recording()

    FrameMarkingConverter(inner).convert(fragment, tmp_path / "frag.typ")

    assert "<deckz-frame>" in inner.converted[0]
    assert fragment.read_text(encoding="utf8") == "# Title\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["frag.md", "frag.typ"]


def test_converter_errors_name_the_fragment(tmp_path: Path) -> None:
    fragment = tmp_path / "frag.md"
    fragment.write_text("# Title\n", encoding="utf8")

    with raises(DeckzError) as error:
        FrameMarkingConverter(_Recording(fail=True)).convert(
            fragment, tmp_path / "frag.typ"
        )

    assert str(error.value).endswith("frag.md")
    assert not (tmp_path / ".frag.frames.md").exists()


def test_converter_fingerprint_differs_from_the_inner_one() -> None:
    assert FrameMarkingConverter(_Recording()).fingerprint() != "inner"
