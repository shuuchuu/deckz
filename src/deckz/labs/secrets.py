"""Find what looks like a credential in a lab notebook.

Lab notebooks are published to a public repository, so a token pasted into
a cell, or printed into a stored output, leaks for good. `find_secrets`
backs the `lab-secrets` content check and `deckz labs publish`'s refusal.

Two kinds of matches: the formats of well-known tokens, and an assignment
to a credential-like name (`api_key = "..."`, `"token": "..."`) of a
literal mixing letters and digits, so that placeholders such as
`"YOUR_API_KEY_HERE"` don't count. A finding never shows the whole value.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_TOKEN_FORMATS = {
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})",
    "Hugging Face token": r"\bhf_[A-Za-z0-9]{30,}",
    # Not any `sk-`: scikit-learn's HTML reprs are full of `sk-toggleable__...`.
    "OpenAI or Anthropic key": (
        r"\bsk-(?:(?:proj|ant|svcacct|admin)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{40,})"
    ),
    "AWS access key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
}
# Each format's fixed text, looked for first: a substring search is far faster
# than a regex over megabytes of stored outputs.
_PREFIXES = {
    "GitHub token": ("gh", "github_pat_"),
    "Hugging Face token": ("hf_",),
    "OpenAI or Anthropic key": ("sk-",),
    "AWS access key": ("AKIA", "ASIA"),
    "Google API key": ("AIza",),
    "Slack token": ("xox",),
    "private key": ("PRIVATE KEY",),
}
_PATTERNS = {name: re.compile(pattern) for name, pattern in _TOKEN_FORMATS.items()}
_KEYWORDS = ("key", "secret", "token", "passw")
# Matched against the lowercased text: a case-insensitive regex is several
# times slower.
_ASSIGNMENT = re.compile(
    r"""(?x)
    (?:api[_-]?key|access[_-]?key|secret|token|password|passwd)\w*
    ["']?\s*[:=]\s*
    ["']([^"'\s]{16,})["']
    """
)
# Stored outputs that can't hold a printed token, and make up most of a
# notebook's bytes.
_BINARY_MIME_PREFIXES = ("image/", "application/pdf", "video/")


@dataclass(frozen=True)
class SecretFinding:
    cell: int
    """Index of the cell, as `deckz labs dump` numbers them."""
    where: str
    """`source` or `outputs`."""
    kind: str
    """What it looks like, e.g. `GitHub token`."""
    masked: str
    """The value's first characters, the rest hidden."""

    def __str__(self) -> str:
        return f"cell [{self.cell}] {self.where}: {self.kind} ({self.masked})"


def _mask(value: str) -> str:
    return f"{value[:4]}…({len(value)} chars)"


def _credential_like(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))


def _text(value: Any) -> str:
    return "".join(value) if isinstance(value, list) else str(value)


def _texts(cell: dict[str, Any]) -> Iterable[tuple[str, str]]:
    yield "source", _text(cell.get("source", ""))
    parts = []
    for output in cell.get("outputs") or []:
        if "text" in output:
            parts.append(_text(output["text"]))
        for mime, data in (output.get("data") or {}).items():
            if not mime.startswith(_BINARY_MIME_PREFIXES):
                parts.append(
                    _text(data) if isinstance(data, (str, list)) else json.dumps(data)
                )
        if "traceback" in output:
            parts.append(_text(output["traceback"]))
    if parts:
        yield "outputs", "\n".join(parts)


def _assignments(text: str) -> Iterable[str]:
    lowered = text.lower()
    if not any(keyword in lowered for keyword in _KEYWORDS):
        return
    # `lower()` keeps ASCII lengths, so spans match the original text; a
    # text whose length changes falls back to a case-insensitive search.
    if len(lowered) == len(text):
        for match in _ASSIGNMENT.finditer(lowered):
            yield text[match.start(1) : match.end(1)]
    else:
        pattern = re.compile(_ASSIGNMENT.pattern, re.VERBOSE | re.IGNORECASE)
        for match in pattern.finditer(text):
            yield match.group(1)


def find_secrets(
    notebook: dict[str, Any], not_secrets: Iterable[str] = ()
) -> list[SecretFinding]:
    """What looks like a credential in `notebook`'s cells.

    Args:
        notebook: The parsed notebook.
        not_secrets: Values known not to be secrets (`labs.not_secrets`).

    Returns:
        One finding per suspicious value and place, in cell order.
    """
    allowed = set(not_secrets)
    findings = []
    for index, cell in enumerate(notebook.get("cells", [])):
        for where, text in _texts(cell):
            seen: set[str] = set()
            for kind, pattern in _PATTERNS.items():
                if not any(prefix in text for prefix in _PREFIXES[kind]):
                    continue
                for match in pattern.finditer(text):
                    value = match.group(0)
                    if value not in allowed and value not in seen:
                        seen.add(value)
                        findings.append(SecretFinding(index, where, kind, _mask(value)))
            for value in _assignments(text):
                if value in allowed or value in seen or not _credential_like(value):
                    continue
                seen.add(value)
                findings.append(
                    SecretFinding(index, where, "credential assignment", _mask(value))
                )
    return findings
