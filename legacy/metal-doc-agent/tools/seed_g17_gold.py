"""Seed G1.7 gold files from run artifacts for review.

The output is a draft, not authoritative: each document still needs the tables,
clauses and items checked against the source pages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import ItemInventory, TableLinkResult  # noqa: E402
from metal_doc_agent.coverage.linker import extract_heading_blocks  # noqa: E402
from metal_doc_agent.extraction.clauses import extract_clauses  # noqa: E402
from metal_doc_agent.items.taxonomy import (  # noqa: E402
    IDENTITY_FACETS_BY_FAMILY,
    UMBRELLA_TERMS,
    normalize_item,
)
from run_loader import load_run  # noqa: E402

CLAUSE_KEYWORDS = ("取样", "检验", "试验方法", "判定", "复验", "交货")
SENTENCE_RE = re.compile(r"[^。；;]+[。；;]?")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--item-gold", default=None)
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    run = load_run(run_dir)
    doc_id = run.document.doc_id or run_dir.name
    inventory = ItemInventory.model_validate_json(
        (run_dir / "item_inventory.json").read_text(encoding="utf-8")
    )
    links = TableLinkResult.model_validate_json(
        (run_dir / "links.json").read_text(encoding="utf-8")
    )
    blocks = extract_heading_blocks(run.pages)
    block_index = {block.clause_id: block for block in blocks if block.clause_id}
    clause_output = extract_clauses(run.pages, run.document)
    clause_index = {clause.clause_id: clause for clause in clause_output.clauses}

    items, unknown_ok = _items(doc_id, inventory, args.item_gold)
    gold_links = _links(links, block_index, run.tables)
    target_clauses = {
        item["clause_id"] for item in gold_links.values() if item.get("clause_id")
    }
    keyword_clauses = {
        clause.clause_id
        for clause in clause_output.clauses
        if any(keyword in (clause.title or "") for keyword in CLAUSE_KEYWORDS)
    }
    clauses = _clauses(target_clauses | keyword_clauses, clause_index, block_index)

    gold = {
        "doc_id": doc_id,
        "items": items,
        "items_unknown_ok": unknown_ok,
        "links": gold_links,
        "link_scope": sorted(gold_links),
        "clauses": clauses,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"doc={doc_id} items={len(items)} links={len(gold_links)} "
        f"clauses={len(clauses)}"
    )
    print(f"out={out_path}")
    return 0


def _items(
    doc_id: str, inventory: ItemInventory, item_gold: str | None
) -> tuple[list[dict], list[str]]:
    if item_gold:
        gold = json.loads(Path(item_gold).read_text(encoding="utf-8"))
        return gold["items"], list(gold.get("unknown_ok") or [])
    items: list[dict] = []
    for item in inventory.items:
        if item.item_family in {"unknown", "inspection"}:
            continue
        if item.status not in {"confirmed", "probable"}:
            continue
        facets = {
            key: item.facets[key]
            for key in IDENTITY_FACETS_BY_FAMILY.get(item.item_family, ())
            if item.facets.get(key)
        }
        items.append(
            {
                "item_canonical": item.item_canonical or item.item_raw,
                "item_family": item.item_family,
                "facets": facets,
                "required": True,
                "note": item.item_raw,
            }
        )
    known = {normalize_item(item["item_canonical"]) for item in items}
    unknown_ok = sorted(
        {
            str(candidate.get("raw", ""))
            for candidate in inventory.unknown_candidates
            if any(term in str(candidate.get("raw", "")) for term in UMBRELLA_TERMS)
        }
        - known
    )
    return _dedupe_items(items), unknown_ok


def _dedupe_items(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (
            normalize_item(item["item_canonical"]),
            item["item_family"],
            tuple(sorted(item.get("facets", {}).items())),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _links(
    links: TableLinkResult, block_index: dict, tables: list
) -> dict[str, dict]:
    captions = {table.table_id: table.caption for table in tables}
    result: dict[str, dict] = {}
    for link in links.links:
        if not link.clause_id:
            continue
        block = block_index.get(link.clause_id)
        quote = None
        if block is not None:
            quote = _table_sentence(block.body) or _table_sentence(block.title)
        if not quote:
            quote = captions.get(link.table_id) or link.evidence or ""
        result[link.table_id] = {
            "clause_id": link.clause_id,
            "quote": quote,
        }
    return result


def _table_sentence(text: str | None) -> str | None:
    if not text:
        return None
    for sentence in SENTENCE_RE.findall(text):
        if "表" in sentence:
            return sentence.strip()
    return None


def _clauses(
    clause_ids: set[str], clause_index: dict, block_index: dict
) -> list[dict]:
    result: list[dict] = []
    for clause_id in sorted(clause_ids, key=_clause_sort_key):
        record = clause_index.get(clause_id)
        block = block_index.get(clause_id)
        fields = {
            key: value.raw
            for key, value in (record.fields.items() if record else [])
        }
        result.append(
            {
                "clause_id": clause_id,
                "kind": _kind(record.title if record else "", block.body if block else ""),
                "quote": (block.body[:200] if block and block.body else (record.title if record else "")),
                "fields": fields,
            }
        )
    return result


def _kind(title: str, body: str) -> str:
    text = f"{title} {body}"
    if "范围" in title:
        return "scope"
    if "规范性引用文件" in title:
        return "normative_reference"
    if "术语" in title:
        return "terms"
    if "取样" in title:
        return "sampling"
    if "检验" in title:
        return "inspection"
    if "试验方法" in title or "方法" in title:
        return "test_method"
    if "包装" in title:
        return "packaging"
    if "交货" in title:
        return "delivery"
    if any(marker in text for marker in ("应符合", "应按", "应不", "技术要求")):
        return "technical_requirement"
    return "other"


def _clause_sort_key(clause_id: str) -> tuple:
    parts = re.findall(r"\d+", clause_id)
    return tuple(int(part) for part in parts), clause_id


if __name__ == "__main__":
    raise SystemExit(main())
