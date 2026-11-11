"""Build pseudo-labelled SFT samples from engine runs (self-training).

Goldset annotations cover 20 documents; the expanded corpus has no human truth.
This builder emits two task types from engine outputs:

* ``row_record``: one record row with evidence-checked values
  (every property points at an existing evidence row of the same table).
* ``header_mapping_constrained``: column roles/properties from the rule
  binding, deduplicated by header signature so repeated layouts do not dominate.

Samples are marked ``pseudo`` and must not be used for evaluation.

Usage:
    python -m tools.build_pseudo_sft --runs runs/corpus_all --out data/m2/pseudo-v2 \
      --header-samples
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from metal_doc_agent.extraction.qwen import ALLOWED_PROPERTIES
from metal_doc_agent.tablegrid.normalize import ELEMENTS, clean_text

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {"mechanical_properties", "chemical_composition"}
HEADER_PROFILES = {
    "chemical_composition",
    "mechanical_properties",
    "inspection",
    "dimension",
    "classification",
}
ROLE_MAP = {
    "row_key": "grade",
    "condition": "condition",
    "measure": "property",
    "row_index": "ignore",
    "method": "ignore",
    "remark": "ignore",
    "unknown": "ignore",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", required=True, help="run root with <doc_id>/result.json")
    parser.add_argument("--out", default=str(ROOT / "data" / "m2" / "pseudo-v2"))
    parser.add_argument("--gold", default=str(ROOT / "goldset" / "v0" / "manifest.json"))
    parser.add_argument("--header-samples", action="store_true")
    parser.add_argument("--max-rows", type=int, default=6000)
    parser.add_argument("--max-headers", type=int, default=600)
    parser.add_argument("--min-binding", type=float, default=0.8)
    args = parser.parse_args(argv)

    runs = Path(args.runs)
    gold_docs = _gold_doc_ids(Path(args.gold))
    train: list[dict] = []
    dev: list[dict] = []
    stats = Counter()
    seen_rows: set[str] = set()
    seen_headers: dict[str, int] = {}
    header_cap = 3
    covered_docs: set[str] = set()
    covered_tables: set[str] = set()
    header_profiles: Counter[str] = Counter()

    for result_path in sorted(runs.glob("*/result.json")):
        doc_id = result_path.parent.name
        if doc_id in gold_docs:
            continue
        rows = _doc_rows(result_path.parent)
        digest = hashlib.sha1(doc_id.encode("utf-8")).hexdigest()
        bucket = dev if int(digest[:2], 16) < 26 else train
        for row in rows:
            key = json.dumps(row["input"], ensure_ascii=False, sort_keys=True) + json.dumps(
                row["output"], ensure_ascii=False, sort_keys=True
            )
            if key in seen_rows:
                stats["row_duplicate"] += 1
                continue
            if len(train) + len(dev) >= args.max_rows:
                break
            seen_rows.add(key)
            row["pseudo"] = True
            bucket.append(row)
            stats["row_samples"] += 1
            covered_docs.add(doc_id)
            covered_tables.add(f"{doc_id}:{row['table_id']}")
        if args.header_samples and sum(seen_headers.values()) < args.max_headers:
            headers = _doc_headers(
                result_path.parent, seen_headers, args.min_binding, header_cap
            )
            for row in headers:
                header_profiles[row["profile"]] += 1
                stats["header_samples"] += 1
                covered_docs.add(doc_id)
                covered_tables.add(f"{doc_id}:{row['table_id']}")
                (dev if bucket is dev else train).append(row)
        if len(train) + len(dev) >= args.max_rows + args.max_headers:
            break

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "train.jsonl", train)
    _write(out / "dev.jsonl", dev)
    _write(out / "heldout.jsonl", [])
    report = {
        "runs": runs.as_posix(),
        "gold_excluded": sorted(gold_docs),
        "train": len(train),
        "dev": len(dev),
        "stats": dict(stats),
        "covered_documents": len(covered_docs),
        "covered_tables": len(covered_tables),
        "header_profiles": dict(header_profiles),
        "notes": (
            "Pseudo labels come from engine output with evidence pointers for "
            "row_record and rule bindings for headers; no human verification. "
            "Use for self-training only, never for accuracy eval."
        ),
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "train": len(train),
                "dev": len(dev),
                "rows": stats["row_samples"],
                "headers": stats["header_samples"],
                "tables": len(covered_tables),
            },
            ensure_ascii=False,
        )
    )
    print(f"out={out}")
    return 0


def _doc_rows(run_dir: Path) -> list[dict]:
    result, evidence, bindings = _load(run_dir)
    if not bindings:
        return []
    doc_id = run_dir.name
    rows: list[dict] = []
    for record in result.get("records") or []:
        table_id = record.get("source_table_id")
        if not table_id:
            continue
        table = _table(run_dir, table_id)
        if table is None:
            continue
        if table.get("profile") not in SUPPORTED or table.get("orientation") != "grade_rows":
            continue
        binding = bindings.get(table_id) or {}
        mapping = _mapping(binding)
        if not mapping:
            continue
        props = record.get("properties") or {}
        if not props or not _evidence_ok(props, table_id, evidence):
            continue
        absolute = min(
            (
                evidence[value["evidence_id"]]["row"]
                for value in props.values()
                if value.get("evidence_id") in evidence
            ),
            default=None,
        )
        if absolute is None:
            continue
        table_rows = table.get("rows") or []
        if absolute >= len(table_rows):
            continue
        raw_row = list(table_rows[absolute])[: len(table["header_paths"])]
        grade_index = next(
            (item["index"] for item in mapping if item["role"] == "grade"), None
        )
        if grade_index is None or grade_index >= len(raw_row):
            continue
        if clean_text(raw_row[grade_index]) != clean_text(record.get("grade")):
            continue
        rows.append(
            {
                "task": "row_record",
                "doc_id": doc_id,
                "table_id": table_id,
                "profile": table["profile"],
                "input": {
                    "header_paths": table["header_paths"],
                    "mapping": {"columns": mapping},
                    "row": raw_row,
                },
                "output": {
                    "grade": record.get("grade"),
                    "condition": record.get("condition"),
                    "properties": {
                        prop: {
                            "raw": value.get("raw"),
                            "comparator": value.get("comparator"),
                            "unit": value.get("unit"),
                        }
                        for prop, value in props.items()
                    },
                },
            }
        )
    return rows


def _doc_headers(
    run_dir: Path, seen: dict[str, int], min_binding: float, cap: int
) -> list[dict]:
    result, _, bindings = _load(run_dir)
    if not bindings:
        return []
    doc_id = run_dir.name
    rows: list[dict] = []
    for table_id, binding in sorted(bindings.items()):
        table = _table(run_dir, table_id)
        if table is None:
            continue
        profile = table.get("profile")
        if profile not in HEADER_PROFILES or table.get("orientation") != "grade_rows":
            continue
        header_paths = table.get("header_paths") or []
        n_cols = int(table.get("n_cols") or len(header_paths))
        if n_cols < 3 or len(header_paths) < 3:
            continue
        mapping = _mapping(binding)
        bound = sum(1 for item in mapping if item["role"] != "ignore")
        if bound / max(1, n_cols) < min_binding:
            continue
        if sum(1 for item in mapping if item["role"] in {"grade", "condition", "property"}) < 2:
            continue
        signature = json.dumps(
            [profile, header_paths, n_cols], ensure_ascii=False, sort_keys=True
        )
        if seen.get(signature, 0) >= cap:
            continue
        seen[signature] = seen.get(signature, 0) + 1
        sample_rows = (table.get("rows") or [])[int(table.get("header_rows") or 1) :][:3]
        rows.append(
            {
                "task": "header_mapping_constrained",
                "doc_id": doc_id,
                "table_id": table_id,
                "profile": profile,
                "pseudo": True,
                "input": {
                    "header_paths": header_paths,
                    "sample_rows": sample_rows,
                    "profile": profile,
                    "orientation": table.get("orientation"),
                    "caption": table.get("caption"),
                    "n_cols": n_cols,
                    "allowed_properties": sorted(ALLOWED_PROPERTIES),
                    "allowed_elements": sorted(ELEMENTS),
                },
                "output": {"columns": mapping},
            }
        )
    return rows


def _load(run_dir: Path) -> tuple[dict, dict, dict]:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    evidence = {}
    evidence_path = run_dir / "evidence.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                evidence[item["evidence_id"]] = item
    bindings_path = run_dir / "column_bindings.json"
    bindings = (
        json.loads(bindings_path.read_text(encoding="utf-8"))
        if bindings_path.exists()
        else {}
    )
    return result, evidence, bindings


def _table(run_dir: Path, table_id: str) -> dict | None:
    path = run_dir / "tablegrid" / f"{table_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(binding: dict) -> list[dict]:
    columns = []
    for item in binding.get("bindings") or []:
        if item.get("status") != "bound":
            columns.append({"index": item["column"], "role": "ignore"})
            continue
        role = ROLE_MAP.get(item.get("role") or "unknown", "ignore")
        column = {"index": item["column"], "role": role}
        if role == "property":
            if not item.get("property"):
                column["role"] = "ignore"
            else:
                column["property"] = item["property"]
                if item.get("unit"):
                    column["unit"] = item["unit"]
        columns.append(column)
    return sorted(columns, key=lambda item: item["index"])


def _evidence_ok(props: dict, table_id: str, evidence: dict) -> bool:
    for value in props.values():
        evidence_id = value.get("evidence_id")
        if not evidence_id or evidence_id not in evidence:
            return False
        if evidence[evidence_id].get("table_id") != table_id:
            return False
        if clean_text(evidence[evidence_id].get("quote")) != clean_text(value.get("raw")):
            return False
    return True


def _gold_doc_ids(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {item["doc_id"] for item in manifest.get("documents") or []}


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
