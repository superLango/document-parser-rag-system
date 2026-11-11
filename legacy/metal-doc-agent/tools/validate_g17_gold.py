"""Validate G1.7 gold files against run pages and table grids."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.coverage.linker import extract_heading_blocks  # noqa: E402
from metal_doc_agent.extraction.clauses import extract_clauses  # noqa: E402
from metal_doc_agent.items.taxonomy import FAMILY_LABELS  # noqa: E402
from run_loader import load_run  # noqa: E402

DEFAULT_GOLD = ROOT / "goldset" / "g1_7" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--docs", nargs="*", default=None)
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    total_errors = 0
    for doc in manifest["docs"]:
        if args.docs and doc["doc_id"] not in args.docs:
            continue
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        run = load_run(Path(args.runs) / doc.get("run", doc["doc_id"]))
        pages_text = _normalize(
            "\n".join(page.markdown for page in run.pages)
        )
        clauses = {
            block.clause_id for block in extract_heading_blocks(run.pages)
        } | {
            clause.clause_id for clause in extract_clauses(run.pages, run.document).clauses
        }
        errors: list[str] = []
        for item in gold.get("items") or []:
            if not item.get("item_canonical"):
                errors.append("item without canonical")
            if item.get("item_family") not in FAMILY_LABELS:
                errors.append(f"unknown family: {item.get('item_family')}")
        for table_id, link in (gold.get("links") or {}).items():
            clause_id = link.get("clause_id")
            if not clause_id:
                errors.append(f"{table_id}: no clause_id")
                continue
            if clause_id not in clauses:
                errors.append(f"{table_id}: clause {clause_id} not found")
            quote = _normalize(link.get("quote") or "")
            if quote and not _quote_found(quote, pages_text):
                errors.append(f"{table_id}: quote not found")
        scope = set(gold.get("link_scope") or [])
        if scope != set(gold.get("links") or {}):
            errors.append("link_scope does not match links")
        for clause in gold.get("clauses") or []:
            clause_id = clause.get("clause_id")
            if clause_id not in clauses:
                errors.append(f"clause {clause_id} not found")
            quote = _normalize(clause.get("quote") or "")
            if quote and not _quote_found(quote, pages_text):
                errors.append(f"clause {clause_id}: quote not found")
        total_errors += len(errors)
        print(
            f"{doc['doc_id']}: items={len(gold.get('items') or [])} "
            f"links={len(gold.get('links') or {})} "
            f"clauses={len(gold.get('clauses') or [])} errors={len(errors)}"
        )
        for error in errors[:10]:
            print(f"  - {error}")
    print(f"total_errors={total_errors}")
    return 1 if total_errors else 0


def _normalize(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    text = text.replace("$", "").replace("\\", "").replace("{", "").replace("}", "")
    text = text.replace("—", "-").replace("–", "-").replace("−", "-")
    text = re.sub(r"\s+", "", text)
    return text.replace("（", "(").replace("）", ")")


def _quote_found(quote: str, pages_text: str) -> bool:
    if quote in pages_text:
        return True
    chunks = re.findall(r"[\u4e00-\u9fff]{6,}", quote)
    return any(chunk in pages_text for chunk in chunks)


if __name__ == "__main__":
    raise SystemExit(main())
