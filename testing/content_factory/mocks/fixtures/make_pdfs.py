"""Generate the tiny fixture PDFs used by the ingest unit test and the
end-to-end integration test. Run once from the repo root:

    python testing/content_factory/mocks/fixtures/make_pdfs.py

Hand-rolled minimal PDF (no third-party writer needed): one text column per
page, Helvetica, simple Tj operators that pdfplumber extracts cleanly.

Object layout is fixed and correct:
    1 Catalog, 2 Pages, 3 Font, then per page: (4+2i) content, (5+2i) page.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "pdfs"


def esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    n_pages = len(pages)
    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n_pages))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for i, page_lines in enumerate(pages):
        stream_lines = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        for line in page_lines:
            stream_lines.append(f"({esc(line)}) Tj T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1")
        content_num = 4 + 2 * i
        page_num = 5 + 2 * i
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_num} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    xref_pos = len(out)
    size = len(objects) + 1
    out += f"xref\n0 {size}\n".encode()
    out += b"0000000000 65535 f \n"
    for num in sorted(objects):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # NCERT-fixture book: prelims carries the class evidence; two chapters.
    make_pdf(
        OUT / "prelims.pdf",
        [
            [
                "Textbook of Science for Class 9",
                "Fixture Edition",
                "FOREWORD",
                "This is a tiny fixture book.",
            ],
            ["CONTENTS", "Chapter 7 Motion", "Chapter 11 Sound"],
        ],
    )
    make_pdf(
        OUT / "ch01.pdf",
        [
            ["CHAPTER 7", "Motion", "We describe motion by distance and displacement."],
            ["Speed is distance divided by time. Velocity is speed with direction."],
            ["Acceleration is the rate of change of velocity. Its SI unit is m/s2."],
            [
                "If a body starts from rest and gains a speed of 10 m/s in 5 s, its acceleration is 2 m/s2."
            ],
            ["Average speed is total distance divided by total time."],
        ],
    )
    make_pdf(
        OUT / "ch02.pdf",
        [
            [
                "CHAPTER 11",
                "Sound",
                "Sound is produced by vibrations and needs a medium.",
            ],
        ],
    )

    # Alternate open book (vector-search supplement): its own motion chapter.
    make_pdf(
        OUT / "alt-open-physics.pdf",
        [
            ["Open Physics Notes (fixture)", "Licensed CC-BY for testing only.", ""],
            ["Chapter on Motion", "Motion can be uniform or accelerated."],
            ["A distance-time graph for uniform motion is a straight line."],
            ["The slope of a distance-time graph gives the speed."],
            ["Velocity-time graphs show acceleration as the slope."],
        ],
    )

    print(f"fixture PDFs written to {OUT}")


if __name__ == "__main__":
    main()
