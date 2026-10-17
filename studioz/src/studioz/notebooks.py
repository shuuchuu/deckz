r"""Lab notebooks rendered as Colab shows them, and compared cell by cell.

Neither nbconvert nor nbdime: a notebook holds few things a page shows, and
studioz renders them itself, one look for the rendering and the comparison,
and no Jupyter stack to install (nbdime's diff is a web app of its own):

- Markdown with markdown-it, its math (`$…$`, `$$…$$`, `\begin{…}`) kept
  whole for MathJax, which typesets it in the browser as Colab does;
- code with Pygments;
- each output's richest type a page shows (nbconvert's order), ANSI colors
  and terminal carriage returns (progress bars) included.

Outputs hold HTML the notebook wrote: the page showing them is served apart,
sandboxed, its scripts limited to studioz's own (`frame_headers`).

The comparison matches cells by Colab's `metadata.id` (or nbformat's `id`),
else by their source: a cell whose source changed but kept its id is one cell
changed, not one removed and one added.
"""

import base64
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markupsafe import Markup, escape
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.python import PythonLexer
from pygments.util import ClassNotFound

_BEGIN = re.compile(r"\\begin\{([^}]+)\}")


def _math(state: StateInline, silent: bool) -> bool:
    # `$…$`, `$$…$$` and `\begin{env}…\end{env}`, untouched by Markdown (`_`
    # and `*` in them aren't emphasis), for MathJax.
    src, start = state.src, state.pos
    if src.startswith("$", start):
        delimiter = "$$" if src.startswith("$$", start) else "$"
        begin = start + len(delimiter)
        end = src.find(delimiter, begin)
        while end > 0 and src[end - 1] == "\\":
            end = src.find(delimiter, end + 1)
        if end <= begin:
            return False
        content, after = src[begin:end], end + len(delimiter)
        display = delimiter == "$$"
    elif match := _BEGIN.match(src, start):
        closing = f"\\end{{{match[1]}}}"
        end = src.find(closing, match.end())
        if end < 0:
            return False
        after = end + len(closing)
        content, display, delimiter = src[start:after], True, ""
    else:
        return False
    if not silent:
        token = state.push("math", "", 0)
        token.content = content
        token.meta = {"display": display, "environment": not delimiter}
    state.pos = after
    return True


def _render_math(self: Any, tokens: Any, idx: int, options: Any, env: Any) -> str:
    token = tokens[idx]
    content = escape(token.content)
    if token.meta["environment"]:
        return str(content)
    return rf"\[{content}\]" if token.meta["display"] else rf"\({content}\)"


def _fence(code: str, lang: str, attrs: Any) -> str:
    try:
        lexer = get_lexer_by_name(lang or "text", stripnl=False)
    except ClassNotFound:
        return ""  # markdown-it's own `<pre><code>`, escaped.
    html = highlight(code, lexer, _FORMATTER)
    return f'<pre class="highlight"><code>{html}</code></pre>'


_FORMATTER = HtmlFormatter(nowrap=True)
_MARKDOWN = MarkdownIt("commonmark", {"html": True, "highlight": _fence}).enable(
    ["table", "strikethrough"]
)
_MARKDOWN.inline.ruler.before("escape", "math", _math)
_MARKDOWN.add_render_rule("math", _render_math)


def markdown(text: str) -> Markup:
    """A Markdown cell's HTML, its math left to MathJax.

    Returns:
        The HTML.
    """
    return Markup(_MARKDOWN.render(text))


def code_lines(code: str) -> list[Markup]:
    """A code cell's source, highlighted, one line at a time.

    Returns:
        Each line's HTML (Pygments closes its spans at each line's end).
    """
    if not code:
        return []
    html = highlight(code, PythonLexer(stripnl=False), _FORMATTER)
    return [Markup(line) for line in html.removesuffix("\n").split("\n")]


_SGR = re.compile(r"\x1b\[([\d;]*)m")
# Every other escape sequence (cursor moves, window titles): dropped.
_OTHER_ESCAPES = re.compile(r"\x1b\[[\d;?]*[A-Za-ln-z]|\x1b\][^\x07]*\x07")
_BOLD, _NORMAL, _EXTENDED, _DEFAULT = 1, 22, {38: "fg", 48: "bg"}, {39: "fg", 49: "bg"}
# SGR's colors: 30-37 and 90-97 the text's, 40-47 and 100-107 the background's.
_COLORS = {
    first + i: (where, i + bright)
    for where, starts in (("fg", (30, 90)), ("bg", (40, 100)))
    for first, bright in zip(starts, (0, 8), strict=True)
    for i in range(8)
}


def _terminal(text: str) -> str:
    # What a terminal would show: a carriage return starts its line again (a
    # progress bar keeps its last state), a backspace erases.
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        kept: list[str] = []
        for char in line.rstrip("\r").rpartition("\r")[2]:
            if char != "\b":
                kept.append(char)
            elif kept:
                kept.pop()
        lines.append("".join(kept))
    return "\n".join(lines)


def _restyle(style: dict[str, str], codes: list[int]) -> None:
    # Apply an SGR sequence's codes: colors among the 16 standard ones and
    # bold are kept, the rest (256 colors past the 16, RGB) skipped.
    while codes:
        code = codes.pop(0)
        if code == 0:
            style.clear()
        elif code == _BOLD:
            style["bold"] = "ansi-bold"
        elif code == _NORMAL:
            style.pop("bold", None)
        elif code in _DEFAULT:
            style.pop(_DEFAULT[code], None)
        elif code in _COLORS:
            where, color = _COLORS[code]
            style[where] = f"ansi-{where}-{color}"
        elif code in _EXTENDED and codes:
            kind = codes.pop(0)
            arguments = codes[:1] if kind == 5 else codes[:3]
            del codes[: len(arguments)]
            if kind == 5 and arguments and arguments[0] < 16:
                style[_EXTENDED[code]] = f"ansi-{_EXTENDED[code]}-{arguments[0]}"


def ansi(text: str) -> Markup:
    """Terminal text as HTML, its colors and bold kept as classes.

    Returns:
        The HTML, to go in a `<pre>`.
    """
    text = _OTHER_ESCAPES.sub("", _terminal(text))
    parts: list[str] = []
    style: dict[str, str] = {}
    position = 0
    for match in _SGR.finditer(text):
        parts.append(_styled(text[position : match.start()], style))
        position = match.end()
        _restyle(style, [int(code) if code else 0 for code in match[1].split(";")])
    parts.append(_styled(text[position:], style))
    return Markup("".join(parts))


def _styled(text: str, style: dict[str, str]) -> str:
    if not text:
        return ""
    if not style:
        return str(escape(text))
    return f'<span class="{" ".join(sorted(style.values()))}">{escape(text)}</span>'


def _text(value: str | list[str]) -> str:
    return "".join(value) if isinstance(value, list) else value


# nbconvert's order: the first a notebook's output has is shown. A widget's
# view needs its kernel: its text (a progress bar's last state) stands in.
_SHOWN = (
    "text/html",
    "text/latex",
    "image/svg+xml",
    "image/png",
    "image/jpeg",
    "image/gif",
    "text/markdown",
    "text/plain",
)


def output(found: dict[str, Any]) -> Markup:
    """One output of a code cell.

    Returns:
        Its HTML, empty for an output with nothing a page shows.
    """
    kind = found.get("output_type")
    if kind == "stream":
        name = "stderr" if found.get("name") == "stderr" else "stdout"
        text = ansi(_text(found.get("text", "")))
        return Markup('<pre class="output {}">{}</pre>').format(name, text)
    if kind == "error":
        traceback = "\n".join(found.get("traceback", ())) or (
            f"{found.get('ename', '')}: {found.get('evalue', '')}"
        )
        return Markup('<pre class="output error">{}</pre>').format(ansi(traceback))
    data = found.get("data", {})
    mime = next((mime for mime in _SHOWN if mime in data), None)
    if mime is None:
        return Markup()
    value = _text(data[mime])
    if mime == "text/html":
        return Markup('<div class="output html">{}</div>').format(Markup(value))
    if mime == "text/latex":
        latex = value.strip().strip("$")
        return Markup('<div class="output latex">\\[{}\\]</div>').format(latex)
    if mime == "text/markdown":
        return Markup('<div class="output markdown">{}</div>').format(markdown(value))
    if mime == "text/plain":
        return Markup('<pre class="output">{}</pre>').format(ansi(value))
    if mime == "image/svg+xml":
        value = base64.b64encode(value.encode()).decode()
    return Markup(
        # Lazy: a figure may be thousands of pixels high, and the notebook
        # has dozens.
        '<div class="output image"><img src="data:{};base64,{}" alt=""'
        ' loading="lazy" decoding="async"></div>'
    ).format(mime, "".join(value.split()))


def _merged(outputs: Sequence[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    # Consecutive writes to one stream show as one block, as in Jupyter.
    pending: dict[str, Any] | None = None
    for found in outputs:
        if (
            pending is not None
            and found.get("output_type") == "stream"
            and found.get("name") == pending.get("name")
        ):
            pending = {**pending, "text": _text(pending["text"]) + _text(found["text"])}
            continue
        if pending is not None:
            yield pending
        pending = found if found.get("output_type") == "stream" else None
        if pending is None:
            yield found
    if pending is not None:
        yield pending


@dataclass(frozen=True)
class Cell:
    kind: str
    """`markdown`, `code` or `raw`."""
    source: str
    count: int | None = None
    """Its execution count, for a code cell run."""
    outputs: tuple[dict[str, Any], ...] = ()
    key: Any = field(default=None, compare=False)
    """What matches it with its other version: its id, else its source."""

    @property
    def html(self) -> Markup:
        """Its source rendered: Markdown as HTML, code highlighted.

        Returns:
            The HTML.
        """
        if self.kind == "markdown":
            return markdown(self.source)
        if self.kind == "code":
            return Markup("\n").join(code_lines(self.source))
        return escape(self.source)

    @property
    def shown_outputs(self) -> tuple[Markup, ...]:
        """Its outputs as HTML, those showing nothing left out.

        Returns:
            Each output's HTML.
        """
        return tuple(
            shown for found in _merged(self.outputs) if (shown := output(found))
        )

    @property
    def outputs_key(self) -> str:
        """Its outputs, their execution counts left out (a rerun changes them).

        Returns:
            Their JSON, to compare with another version's.
        """
        return json.dumps(
            [
                {k: v for k, v in o.items() if k != "execution_count"}
                for o in self.outputs
            ],
            sort_keys=True,
        )


def cells(notebook: dict[str, Any]) -> list[Cell]:
    """The notebook's cells.

    Returns:
        Each cell, in order.
    """
    found = []
    for cell in notebook.get("cells", ()):
        kind = cell.get("cell_type", "raw")
        source = _text(cell.get("source", ""))
        key = cell.get("metadata", {}).get("id") or cell.get("id") or (kind, source)
        found.append(
            Cell(
                kind,
                source,
                cell.get("execution_count"),
                tuple(cell.get("outputs", ())),
                key,
            )
        )
    return found


@dataclass(frozen=True)
class Line:
    html: Markup
    mark: Literal["", "del", "ins"] = ""


@dataclass(frozen=True)
class Change:
    """A step of a comparison: cells unchanged, or a cell changed, added, removed."""

    kind: Literal["same", "changed", "added", "removed"]
    before: Cell | None = None
    after: Cell | None = None
    same: tuple[Cell, ...] = ()
    """The run of unchanged cells, for `same`."""

    @property
    def source_changed(self) -> bool:
        return (
            self.before is not None
            and self.after is not None
            and (self.before.source != self.after.source)
        )

    @property
    def outputs_changed(self) -> bool:
        return (
            self.before is not None
            and self.after is not None
            and (self.before.outputs_key != self.after.outputs_key)
        )

    @property
    def lines(self) -> tuple[list[Line], list[Line]]:
        """Both versions' sources, line by line, what changed marked.

        Returns:
            The lines before, and after.
        """
        assert self.before is not None
        assert self.after is not None
        return marked(self.before, self.after)


def _words(line: str) -> list[str]:
    return re.findall(r"\s+|\w+|[^\w\s]", line)


def _word_marks(old: str, new: str) -> tuple[Markup, Markup]:
    # The words of a reworded line that changed.
    a, b = _words(old), _words(new)
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        removed, added = escape("".join(a[i1:i2])), escape("".join(b[j1:j2]))
        if tag == "equal":
            left.append(removed)
            right.append(added)
            continue
        if removed:
            left.append(f'<span class="word-del">{removed}</span>')
        if added:
            right.append(f'<span class="word-ins">{added}</span>')
    return Markup("".join(left)), Markup("".join(right))


def marked(before: Cell, after: Cell) -> tuple[list[Line], list[Line]]:
    """Two versions of a cell's source, line by line, what changed marked.

    Code is highlighted; in prose (Markdown), where a line is a paragraph, a
    reworded line also marks the words that changed.

    Returns:
        The lines before, and after.
    """
    old, new = before.source.split("\n"), after.source.split("\n")
    code = before.kind == after.kind == "code"
    shown_old = code_lines(before.source) if code else [escape(line) for line in old]
    shown_new = code_lines(after.source) if code else [escape(line) for line in new]
    left: list[Line] = []
    right: list[Line] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            left += [Line(line) for line in shown_old[i1:i2]]
            right += [Line(line) for line in shown_new[j1:j2]]
            continue
        olds, news = shown_old[i1:i2], shown_new[j1:j2]
        if tag == "replace" and not code:
            for k in range(min(len(olds), len(news))):
                olds[k], news[k] = _word_marks(old[i1 + k], new[j1 + k])
        left += [Line(line, "del") for line in olds]
        right += [Line(line, "ins") for line in news]
    return left, right


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    """The notebook's changes, cell by cell.

    Returns:
        Each run of unchanged cells, and each cell changed (its source or its \
        outputs), added or removed, in the notebook's order.
    """
    old, new = cells(before), cells(after)
    steps: list[Change] = []
    matcher = SequenceMatcher(
        None, [cell.key for cell in old], [cell.key for cell in new], autojunk=False
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        olds, news = old[i1:i2], new[j1:j2]
        if tag == "equal":
            steps += [_pair(a, b) for a, b in zip(olds, news, strict=True)]
            continue
        # Cells of the same kind at the same place: one cell changed.
        while olds and news and olds[0].kind == news[0].kind:
            steps.append(_pair(olds.pop(0), news.pop(0)))
        steps += [Change("removed", before=cell) for cell in olds]
        steps += [Change("added", after=cell) for cell in news]
    merged: list[Change] = []
    for step in steps:
        if step.kind == "same" and merged and merged[-1].kind == "same":
            merged[-1] = Change("same", same=(*merged[-1].same, *step.same))
        else:
            merged.append(step)
    return merged


def _pair(before: Cell, after: Cell) -> Change:
    if before.source == after.source and before.outputs_key == after.outputs_key:
        return Change("same", same=(after,))
    return Change("changed", before=before, after=after)


def frame_headers(origin: str) -> dict[str, str]:
    """The headers of a page showing a notebook.

    Sandboxed (an origin of its own, so its HTML can't reach studioz's
    routes), only studioz's own scripts and styles (MathJax), images from
    anywhere (a Markdown cell's), no form, no request.

    Args:
        origin: studioz's, as the browser names it (`http://localhost:8421`).

    Returns:
        Its `Content-Security-Policy`.
    """
    static = f"{origin}/static/"
    return {
        "Content-Security-Policy": "; ".join(
            (
                "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox",
                "default-src 'none'",
                f"script-src {static}",
                f"style-src {static} 'unsafe-inline'",
                "img-src * data:",
                "form-action 'none'",
                "base-uri 'none'",
            )
        ),
        "Cache-Control": "no-cache",
    }
