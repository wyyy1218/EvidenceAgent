"""Generate binary PDF fixtures for S10/S11 tests."""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def write_minimal_text_pdf(path: Path, lines: list[str]) -> None:
    """Write a tiny uncompressed PDF with Helvetica text (Latin-1 safe for stream)."""
    # Use simple PDF with one page; Chinese goes via UTF-16BE hex strings if needed.
    # For reliability in fixtures, use ASCII content in content stream.
    y = 750
    content_cmds = ["BT", "/F1 12 Tf"]
    for line in lines:
        safe = line.encode("latin-1", errors="replace").decode("latin-1")
        content_cmds.append(f"50 {y} Td ({safe}) Tj")
        content_cmds.append("0 -18 Td")
        y -= 18
    content_cmds.append("ET")
    stream = "\n".join(content_cmds).encode("latin-1")

    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(bytes(out))


def write_blank_pdf(path: Path, pages: int = 1) -> None:
    """PDF with empty content streams — triggers needs_ocr."""
    kids = " ".join(f"{3+i} 0 R" for i in range(pages))
    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(
        f"2 0 obj<< /Type /Pages /Kids [{kids}] /Count {pages} >>endobj\n".encode("ascii")
    )
    for i in range(pages):
        page_num = 3 + i
        content_num = 3 + pages + i
        objects.append(
            f"{page_num} 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_num} 0 R >>endobj\n".encode("ascii")
        )
    for i in range(pages):
        content_num = 3 + pages + i
        stream = b"BT ET"
        objects.append(
            f"{content_num} 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(bytes(out))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_minimal_text_pdf(
        OUT / "sample_text.pdf",
        ["Offline deploy OK", "Scheme A works without network."],
    )
    write_blank_pdf(OUT / "scan_like.pdf", pages=2)
    # disguised: text file with .pdf name handled in tests via bytes
    (OUT / "empty.txt").write_bytes(b"")
    (OUT / "bad_encoding.txt").write_bytes(b"\xff\xfe not utf8 \x80\x81")
    (OUT / "disguised.pdf").write_bytes(b"this is not a pdf at all")
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main()
