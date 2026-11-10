"""Export a human-review JSON comparing machine records with gold annotations.

Each document lists tables and records; every field carries the machine value,
gold value, evidence pointer and a ``match`` flag, so a reviewer can verify
accuracy without opening the pipeline artifacts.

Usage:
    python -m tools.export_manual_review --runs runs/adapter_v3_gold \
      --gold goldset/v0 --out eval/manual-review/adapter-v3-gold.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import DocumentResult, Evidence
from metal_doc_agent.tablegrid.normalize import clean_text

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--gold", default=str(ROOT / "goldset" / "v0"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--md", default="")
    args = parser.parse_args(argv)

    runs = Path(args.runs)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    gold_docs = {item["doc_id"]: item for item in manifest.get("documents") or []}
    documents = []
    totals = {
        "fields": 0,
        "match": 0,
        "mismatch": 0,
        "gold_only": 0,
        "extra_fields": 0,
        "extra_records": 0,
    }
    for result_path in sorted(runs.glob("*/result.json")):
        doc_id = result_path.parent.name
        gold_meta = gold_docs.get(doc_id)
        if not gold_meta:
            continue
        annotation = json.loads(
            (gold_dir / gold_meta["annotation_file"]).read_text(encoding="utf-8")
        )
        result = DocumentResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        evidence = _evidence(result_path.parent / "evidence.jsonl")
        gold_tables = {item["table_id"]: item for item in annotation.get("tables") or []}
        machine_by_table: dict[str, list] = {}
        for record in result.records:
            machine_by_table.setdefault(record.source_table_id, []).append(record)
        tables = []
        for table in result.tables:
            gold_table = gold_tables.get(table.table_id)
            if not gold_table:
                continue
            machine_records = machine_by_table.get(table.table_id, [])
            gold_records = gold_table.get("records") or []
            rows, counts, extras = _records(machine_records, gold_records, evidence)
            for key in totals:
                totals[key] += counts[key]
            tables.append(
                {
                    "table_id": table.table_id,
                    "page_no": table.page_no,
                    "caption": table.caption,
                    "profile": table.profile,
                    "orientation": table.orientation,
                    "header_paths": table.header_paths,
                    "counts": counts,
                    "records": rows,
                    "machine_extra_records": extras,
                }
            )
        documents.append(
            {
                "doc_id": doc_id,
                "title": gold_meta.get("title"),
                "standard_no": gold_meta.get("standard_no"),
                "doc_type": gold_meta.get("doc_type"),
                "tables": tables,
            }
        )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": runs.as_posix(),
        "gold": gold_dir.as_posix(),
        "totals": totals,
        "documents": documents,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"documents": len(documents), **totals}, ensure_ascii=False))
    print(f"out={out}")
    return 0


def _records(machine_records, gold_records, evidence) -> tuple[list[dict], dict, list[dict]]:
    counts = {"fields": 0, "match": 0, "mismatch": 0, "gold_only": 0, "extra_fields": 0, "extra_records": 0}
    used: set[int] = set()
    rows = []
    extras = []
    for gold in gold_records:
        index = _best_match(gold, machine_records, used)
        machine = machine_records[index] if index is not None else None
        if index is not None:
            used.add(index)
        fields, extra = _fields(machine, gold, evidence, counts)
        rows.append(
            {
                "record_id": (machine.record_id if machine else None),
                "grade": gold.get("grade"),
                "condition": gold.get("condition"),
                "machine_condition": (machine.condition if machine else None),
                "fields": fields,
                "machine_extra_fields": extra,
            }
        )
    for index, machine in enumerate(machine_records):
        if index in used:
            continue
        counts["extra_records"] += 1
        extras.append(
            {
                "record_id": machine.record_id,
                "grade": machine.grade,
                "condition": machine.condition,
                "fields": [
                    {"property": prop, "machine": _value(value, evidence, machine)}
                    for prop, value in sorted(machine.properties.items())
                ],
            }
        )
    return rows, counts, extras


def _best_match(gold, machine_records, used: set[int]) -> int | None:
    grade = clean_text(gold.get("grade"))
    condition = clean_text(gold.get("condition"))
    candidates = [
        index
        for index, record in enumerate(machine_records)
        if index not in used and clean_text(record.grade) == grade
    ]
    if not candidates:
        return None
    if condition:
        for index in candidates:
            if condition in clean_text(machine_records[index].condition) or clean_text(
                machine_records[index].condition
            ) in condition:
                return index
    return candidates[0]


def _fields(machine, gold, evidence, counts) -> tuple[list[dict], list[dict]]:
    machine_props = machine.properties if machine else {}
    gold_props = (gold or {}).get("properties") or {}
    fields = []
    for prop in sorted(gold_props):
        gold_value = gold_props.get(prop)
        machine_value = machine_props.get(prop)
        counts["fields"] += 1
        if machine_value is not None:
            matched = _same(machine_value, gold_value)
            counts["match" if matched else "mismatch"] += 1
        else:
            matched = False
            counts["gold_only"] += 1
        fields.append(
            {
                "property": prop,
                "match": matched,
                "machine": _value(machine_value, evidence, machine),
                "gold": _value(gold_value, None, None),
            }
        )
    extra = [
        {"property": prop, "machine": _value(value, evidence, machine)}
        for prop, value in sorted(machine_props.items())
        if prop not in gold_props
    ]
    counts["extra_fields"] += len(extra)
    return fields, extra


def _value(value, evidence, machine) -> dict | None:
    if value is None:
        return None
    payload = {
        "raw": _attr(value, "raw"),
        "comparator": _attr(value, "comparator"),
        "value": _attr(value, "value"),
        "lower": _attr(value, "lower"),
        "upper": _attr(value, "upper"),
        "unit": _attr(value, "unit"),
        "text": _attr(value, "text"),
    }
    evidence_id = _attr(value, "evidence_id")
    if evidence_id:
        payload["evidence_id"] = evidence_id
        item = evidence.get(evidence_id)
        if item:
            payload["evidence"] = {
                "page_no": item.page_no,
                "table_id": item.table_id,
                "row": item.row,
                "col": item.col,
                "quote": item.quote,
            }
    gold_evidence = _attr(value, "evidence")
    if isinstance(gold_evidence, dict):
        payload["gold_evidence"] = gold_evidence
    condition = _attr(value, "condition")
    if condition:
        payload["condition"] = condition
    return payload


def _same(left, right) -> bool:
    return all(
        _norm(_attr(left, key)) == _norm(_attr(right, key))
        for key in ("comparator", "value", "lower", "upper", "unit", "text")
    )


def _attr(value, key):
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _norm(value):
    if isinstance(value, str):
        return clean_text(value)
    return value


def _evidence(path: Path) -> dict[str, Evidence]:
    if not path.exists():
        return {}
    return {
        item.evidence_id: item
        for item in (
            Evidence.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


if __name__ == "__main__":
    raise SystemExit(main())
