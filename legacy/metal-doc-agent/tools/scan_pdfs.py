"""Scan corpus PDFs and report whether each page has a text layer.

Used to classify documents as digital-native vs scanned for the goldset
manifest. Requires the optional `pdf` extra (pypdf).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

logging.getLogger("pypdf").setLevel(logging.ERROR)

from pypdf import PdfReader  # noqa: E402


def scan(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    counts = []
    for page in reader.pages:
        try:
            counts.append(len((page.extract_text() or "").strip()))
        except Exception:
            counts.append(0)
    nonempty = [c for c in counts if c > 0]
    total = sum(counts)
    pages = len(counts)
    if pages and len(nonempty) / pages >= 0.8 and total / pages >= 200:
        source_type = "digital_native"
    elif pages and total / pages < 30:
        source_type = "scanned"
    else:
        source_type = "hybrid"
    return {
        "pages": pages,
        "total_chars": total,
        "chars_per_page": round(total / pages, 1) if pages else 0,
        "pages_with_text": len(nonempty),
        "text_ratio": round(len(nonempty) / pages, 3) if pages else 0,
        "source_type": source_type,
    }


def main(root: str, out: str | None = None) -> None:
    root_path = Path(root)
    rows = []
    for pdf in sorted(root_path.rglob("*.pdf")):
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
        info = scan(pdf)
        info.update(
            {
                "file": str(pdf.relative_to(root_path)),
                "sha256_12": digest,
                "size_mb": round(pdf.stat().st_size / 1024 / 1024, 2),
            }
        )
        rows.append(info)
        print(
            f"{info['source_type']:<14} {info['pages']:>3}p "
            f"{info['chars_per_page']:>7} {info['file'][:58]}"
        )
    if out:
        Path(out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {out}")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else r"f:\hanson\hanson_doc_parse\标准文件"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    main(root, out)
