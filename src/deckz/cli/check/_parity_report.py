"""Render a `ParityReport` as a static HTML page, for a human to open and scan.

Kept separate from `analyzing.parity` (which only returns structured data):
deckz's core never renders anything for a person to look at, see
`cli/_presentation.py`'s module boundary -- this is the same idea, just for
a browser page instead of a terminal one.
"""

from html import escape
from pathlib import Path

from ...analyzing.parity import ParityReport

_PAGE = """\
<!doctype html>
<meta charset="utf-8">
<title>Parity report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 14px/1.4 system-ui, sans-serif; margin: 2rem; }}
  h1 {{ font-size: 1.1rem; }}
  .summary {{ margin-bottom: 1rem; }}
  .summary .warn {{ color: #b45309; font-weight: bold; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border-bottom: 1px solid #8884; padding: 0.4rem 0.6rem; \
vertical-align: top; text-align: left; }}
  th button {{ font: inherit; font-weight: bold; background: none; border: none; \
cursor: pointer; padding: 0; color: inherit; }}
  th button:hover {{ text-decoration: underline; }}
  td.slide {{ font-variant-numeric: tabular-nums; }}
  td.gap {{ font-variant-numeric: tabular-nums; }}
  tr.shrunk {{ background: #f59e0b22; }}
  .shrunk-badge {{ font-size: 0.8em; color: #b45309; }}
  img {{ max-width: 320px; max-height: 240px; display: block; }}
  ul.problems li {{ font-family: monospace; font-size: 0.85em; }}
</style>
<h1>Parity report</h1>
<div class="summary">
  <p>{summary}</p>
  {problems}
</div>
<table id="parity">
  <thead>
    <tr>
      <th><button data-sort="slide">Slide</button></th>
      <th><button data-sort="gap">Gap ▾</button></th>
      <th>PDF</th>
      <th>HTML</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<script>
  const tbody = document.querySelector("#parity tbody");
  const rows = () => [...tbody.rows];
  let ascending = false;
  document.querySelectorAll("th button").forEach((button) => {{
    button.addEventListener("click", () => {{
      const key = button.dataset.sort;
      ascending = button.dataset.ascending === "true" ? false : true;
      document.querySelectorAll("th button").forEach((b) => delete b.dataset.ascending);
      button.dataset.ascending = String(ascending);
      const sorted = rows().sort((a, b) => {{
        const x = Number(a.dataset[key]), y = Number(b.dataset[key]);
        return ascending ? x - y : y - x;
      }});
      sorted.forEach((row) => tbody.appendChild(row));
    }});
  }});
</script>
"""

_ROW = """\
    <tr class="{row_class}" data-slide="{slide}" data-gap="{gap}">
      <td class="slide">{slide}{badge}</td>
      <td class="gap">{gap:.2f}</td>
      <td><img src="pdf/{slide:03}.png" loading="lazy" alt="PDF slide {slide}"></td>
      <td><img src="html/{slide:03}.png" loading="lazy" alt="HTML slide {slide}"></td>
    </tr>
"""


def _shrunk_slides(report: ParityReport) -> set[int]:
    shrunk = set()
    for line in report.shrunk:
        index, _, _ = line.partition(":")
        if index.strip().isdigit():
            shrunk.add(int(index))
    return shrunk


def write_html_report(report: ParityReport) -> Path:
    """Write `report` as `report.out_dir / "report.html"`.

    Returns:
        The report's path.
    """
    shrunk_slides = _shrunk_slides(report)
    rows = "".join(
        _ROW.format(
            slide=slide,
            gap=report.diffs[slide],
            row_class="shrunk" if slide in shrunk_slides else "",
            badge=' <span class="shrunk-badge">shrunk</span>'
            if slide in shrunk_slides
            else "",
        )
        for slide in report.compared
    )
    summary = (
        f"{len(report.compared)} slides compared, mean diff {report.mean_diff:.2f} "
        f"-- {report.pages} PDF pages, {report.slides} HTML slides, "
        f"{len(shrunk_slides)} frame(s) shrunk to fit"
    )
    if report.mismatched:
        summary = f'<span class="warn">SLIDE COUNT MISMATCH</span> -- {summary}'
    problems = ""
    if report.problems:
        items = "".join(f"<li>{escape(p)}</li>" for p in report.problems)
        problems = f'<ul class="problems">{items}</ul>'
    page = _PAGE.format(summary=summary, problems=problems, rows=rows)
    path = report.out_dir / "report.html"
    path.write_text(page, encoding="utf8")
    return path
