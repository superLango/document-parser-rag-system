"""Build an agent-annotated goldset from engine runs (no human labels).

The annotator replays the deterministic extractor on the run's TableGrid and
keeps only records whose every value quote matches its evidence row. It is an
agent annotation (rules + evidence verification), not a human double-blind
label; it is used for training and for a separate heldout check.

Usage:
    python -m tools.build_agent_gold --runs runs/corpus_all \
      --out goldset/agent-v1 --limit 40
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from metal_doc_agent.contracts import DocumentMeta, TableGrid
from metal_doc_agent.extraction.mock import MockExtractor
from metal_doc_agent.tablegrid.normalize import clean_text
from metal_doc_agent.tablegrid.profile import annotate_table

ROOT = Path(__file__).resolve().parents[1]
# The gold schema has a closed doc_type enum; keep the corpus taxonomy in the
# per-document note and store the canonical value here.
DOC_TYPE_MAP = {
    "technical_condition": "agreement",
    "manufacturing_outline": "other",
    "uncatalogued": "other",
    "internal_document": "other",
    "national_or_industry_standard": "other",
    "enterprise_standard": "enterprise",
}
TYPE_QUOTAS = {
    "technical_condition": 12,
    "manufacturing_outline": 10,
    "uncatalogued": 14,
    "internal_document": 2,
    "national_or_industry_standard": 2,
}
SPLITS = ("mini", "mini", "mini", "dev", "heldout")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "corpus_all"))
    parser.add_argument("--out", default=str(ROOT / "goldset" / "agent-v1"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--min-records", type=int, default=2)
    parser.add_argument(
        "--reuse",
        default="",
        help="re-annotate the documents of an existing goldset instead of re-selecting",
    )
    args = parser.parse_args(argv)

    runs = Path(args.runs)
    gold_v0 = _gold_docs(ROOT / "goldset" / "v0" / "manifest.json")
    doc_types = _doc_types()
    split_by_doc: dict[str, str] = {}
    type_by_doc: dict[str, str] = {}
    if args.reuse:
        old = json.loads(
            (Path(args.reuse) / "manifest.json").read_text(encoding="utf-8")
        )
        selected: list[tuple[str, dict]] = []
        for entry in old.get("documents") or []:
            doc_id = entry["doc_id"]
            annotation = _annotate(runs / doc_id)
            if not annotation:
                print("skip (no annotation)", doc_id)
                continue
            selected.append((doc_id, annotation))
            split_by_doc[doc_id] = entry.get("split", "dev")
            note = entry.get("notes") or ""
            type_by_doc[doc_id] = note.split(";")[0].strip() or doc_types.get(
                doc_id, "uncatalogued"
            )
        if not selected:
            print("no documents to reuse")
            return 1
        candidates = selected
        by_type = {}
    else:
        candidates = []
        for result_path in sorted(runs.glob("*/result.json")):
            doc_id = result_path.parent.name
            if doc_id in gold_v0:
                continue
            annotation = _annotate(result_path.parent)
            if annotation and annotation["_records"] >= args.min_records:
                candidates.append((doc_id, annotation))
        candidates.sort(key=lambda item: (-item[1]["_records"], item[0]))

        by_type: dict[str, list] = defaultdict(list)
        for doc_id, annotation in candidates:
            by_type[doc_types.get(doc_id, "uncatalogued")].append((doc_id, annotation))
        selected: list[tuple[str, dict]] = []
        used: set[str] = set()
        for doc_type, quota in TYPE_QUOTAS.items():
            for doc_id, annotation in by_type.get(doc_type, []):
                if len(selected) >= args.limit or quota <= 0:
                    break
                selected.append((doc_id, annotation))
                used.add(doc_id)
                quota -= 1
        for doc_id, annotation in candidates:
            if len(selected) >= args.limit:
                break
            if doc_id not in used:
                selected.append((doc_id, annotation))
    if not selected:
        print("no candidates")
        return 1

    out = Path(args.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    documents = []
    for index, (doc_id, annotation) in enumerate(selected):
        split = split_by_doc.get(doc_id) or SPLITS[index % len(SPLITS)]
        raw_type = type_by_doc.get(doc_id) or doc_types.get(doc_id, "uncatalogued")
        payload = _document_payload(runs / doc_id, doc_id, annotation)
        (out / "docs" / f"{doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        documents.append(
            {
                "doc_id": doc_id,
                "standard_no": payload.get("standard_no"),
                "title": payload.get("title"),
                "doc_type": DOC_TYPE_MAP.get(raw_type, "other"),
                "source_type": "hybrid",
                "material": None,
                "product_form": None,
                "md_path": payload.get("source_path"),
                "pages": payload.get("pages"),
                "tables": len(payload["tables"]),
                "profiles": sorted({t["profile"] for t in payload["tables"]}),
                "split": "mini" if split == "mini" else split,
                "priority": 1,
                "annotation_status": "annotated",
                "annotation_file": f"docs/{doc_id}.json",
                "notes": (
                    f"{raw_type}; "
                    "agent rules + evidence verification; not human double-blind"
                ),
            }
        )
    manifest = {
        "schema_version": "agent-1.0.0",
        "created_at": "2026-10-30",
        "corpus_root": str(runs),
        "documents": documents,
        "summary": {
            "documents": len(documents),
            "records": sum(item["_records"] for _, item in selected),
            "by_split": dict(Counter(doc["split"] for doc in documents)),
            "by_doc_type": dict(Counter(doc["doc_type"] for doc in documents)),
            "by_profile": dict(
                Counter(
                    table["profile"]
                    for _, item in selected
                    for table in item["tables"]
                )
            ),
        },
        "notes": [
            "Agent-annotated goldset for training and heldout checking.",
            "Values were verified against evidence quotes; not a human double-blind label.",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False))
    print(f"out={out}")
    return 0


def _annotate(run_dir: Path) -> dict | None:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    document = DocumentMeta.model_validate(result["document"])
    evidence = _evidence(run_dir / "evidence.jsonl")
    extractor = MockExtractor()
    tables = []
    records = 0
    for table in result.get("tables") or []:
        if table.get("profile") not in {"chemical_composition", "mechanical_properties"}:
            continue
        grid = TableGrid.model_validate_json(
            (run_dir / "tablegrid" / f"{table['table_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        grid = annotate_table(grid)
        output = extractor.extract(grid, document)
        table_records = [_record(record, evidence, grid) for record in output.records]
        table_records = [item for item in table_records if item]
        if not table_records:
            continue
        records += len(table_records)
        tables.append(
            {
                "table_id": grid.table_id,
                "page_no": grid.page_no,
                "caption": grid.caption,
                "profile": grid.profile,
                "orientation": grid.orientation,
                "scope": "full",
                "note": None,
                "records": table_records,
                "inspection_items": [],
                "classification_items": [],
            }
        )
    if not tables:
        return None
    return {
        "_records": records,
        "tables": tables,
        "standard_no": result["document"].get("standard_no"),
        "title": result["document"].get("title"),
        "pages": result["document"].get("page_count"),
        "source_path": result["document"].get("source_path"),
    }


def _record(record, evidence, grid: TableGrid | None = None) -> dict | None:
    props = {}
    for prop, value in record.properties.items():
        item = evidence.get(value.evidence_id)
        if item is None and grid is not None:
            # New rule paths extract cells the original run never touched, so
            # their evidence id is absent from evidence.jsonl. The grid cell is
            # the same source of truth, so rebuild the pointer from it.
            item = _grid_evidence(grid, value.evidence_id)
        if item is None:
            return None
        if (item.get("quote") or "").strip() != (value.raw or "").strip():
            return None
        props[prop] = {
            "raw": value.raw,
            "value": value.value,
            "text": value.text,
            "unit": value.unit,
            "comparator": value.comparator,
            "lower": value.lower,
            "upper": value.upper,
            "condition": value.condition,
            "evidence": {
                "page_no": item.get("page_no"),
                "table_id": item.get("table_id"),
                "row": item.get("row"),
                "col": item.get("col"),
                "clause_id": None,
                "quote": item.get("quote"),
            },
        }
    if not props:
        return None
    record_id = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", record.record_id)
    return {
        "record_id": record_id,
        "grade": record.grade,
        "grade_level": record.grade_level,
        "condition": record.condition,
        "facets": {},
        "properties": props,
    }


def _document_payload(run_dir: Path, doc_id: str, annotation: dict) -> dict:
    manifest_path = run_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "schema_version": "agent-1.0.0",
        "doc_id": doc_id,
        "standard_no": annotation.get("standard_no") or manifest.get("standard_no"),
        "title": annotation.get("title") or manifest.get("title"),
        "doc_type": DOC_TYPE_MAP.get(manifest.get("doc_type"), "other"),
        "material": manifest.get("material"),
        "product_form": manifest.get("product_form"),
        "source_type": "hybrid",
        "pages": annotation.get("pages"),
        "source_path": annotation.get("source_path"),
        "annotation": {
            "status": "reviewed",
            "annotator": "engine-rules+evidence-audit",
            "notes": ["values verified against evidence quotes; not human double-blind"],
        },
        "tables": annotation["tables"],
    }


def _grid_evidence(grid: TableGrid, evidence_id: str) -> dict | None:
    """Rebuild an evidence pointer from ``ev:doc:table:rN:cM`` id + grid cell."""
    parts = evidence_id.split(":")
    if len(parts) < 3 or not parts[-2].startswith("r") or not parts[-1].startswith("c"):
        return None
    try:
        row = int(parts[-2][1:])
        col = int(parts[-1][1:])
    except ValueError:
        return None
    if row < 0 or row >= len(grid.rows) or col >= len(grid.rows[row]):
        return None
    return {
        "page_no": grid.page_no,
        "table_id": grid.table_id,
        "row": row,
        "col": col,
        "quote": clean_text(grid.rows[row][col]),
    }


def _evidence(path: Path) -> dict:
    if not path.exists():
        return {}
    items = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        items[item["evidence_id"]] = item
    return items


def _gold_docs(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {item["doc_id"] for item in manifest.get("documents") or []}


def _doc_types() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in (
        ROOT / "runs" / "corpus_ext" / "selection.json",
        ROOT / "runs" / "corpus_v2" / "selection.json",
        ROOT / "runs" / "corpus_v3" / "selection.json",
    ):
        if not path.exists():
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            mapping[item["slug"]] = item.get("doc_type") or "uncatalogued"
    return mapping


if __name__ == "__main__":
    raise SystemExit(main())
