"""Tiny PDFs for the tests, and for the fake builds they run."""

from pathlib import Path


def write_pdf(path: Path, boxes: list[tuple[int, int]]) -> None:
    """A PDF with a page per box, a black square at `(x, y)` from bottom left."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(boxes)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(boxes)} >>")
    for i, (x, y) in enumerate(boxes):
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] "
            f"/Contents {4 + 2 * i} 0 R >>"
        )
        stream = f"0 g {x} {y} 30 30 re f"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(out)
