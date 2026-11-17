"""Print gold PDF clauses/inventory entries matching keywords."""

import json
import os
import sys
from pathlib import Path

RUNTIME_DIR = Path(os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime"))
sys.path.insert(0, str(RUNTIME_DIR))

import builtin
import clauses as clauses_module
import inventory as inventory_module


def resolve_pdf(raw: str) -> Path:
    path = Path(str(raw or ""))
    if path.exists():
        return path
    text = str(raw or "").replace("\\", "/")
    marker = "/hanson_doc_parse/"
    if marker in text:
        return Path("/data") / text.split(marker, 1)[1]
    return path


def main() -> int:
    doc_id = sys.argv[1]
    keywords = [item for item in sys.argv[2:] if item]
    root = Path(os.environ.get("GOLD_DIR", "/data/gold_standard_30"))
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    item = next(x for x in index["documents"] if x["doc_id"] == doc_id)
    pdf = resolve_pdf(item["source_pdf"])
    import fitz

    pages = []
    with fitz.open(pdf) as document:
        for page in document:
            pages.append(page.get_text("text"))
    markdown = "\n".join(pages)
    builtin._DOCUMENT_TEXT_CACHE = markdown
    ocr = {
        "markdown": markdown,
        "pages": [
            {"page_no": index, "markdown": text}
            for index, text in enumerate(pages, start=1)
        ],
        "tables": [],
    }
    payload = clauses_module.extract_clauses(ocr)
    print("== clauses", payload["stats"])
    for clause in payload["clauses"]:
        text = f"{clause.get('title')} {clause.get('text')}"
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        print(
            f"{clause['clause_id']} [{clause['kind']}] {clause.get('title')} "
            f":: {str(clause.get('text'))[:200]}"
        )
        print(
            "   fields:",
            json.dumps(clause.get("fields"), ensure_ascii=False)[:300],
        )
    inspections = builtin._inspection_items(ocr)
    inv = inventory_module.build_inventory([], payload, inspections, ocr)
    print("== inventory", len(inv["items"]), json.dumps(inv.get("coverage"), ensure_ascii=False))
    for entry in inv["items"]:
        text = f"{entry.get('item')} {entry.get('requirement')} " + " ".join(
            str(row.get("text") or "") for row in entry.get("requirements") or []
        )
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        print(
            f"- {entry.get('feature')} | {entry.get('item')} | "
            f"{str(entry.get('requirement') or '')[:120]} | "
            f"reqs={len(entry.get('requirements') or [])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
