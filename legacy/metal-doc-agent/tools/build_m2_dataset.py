"""Build M2.1 supervised samples from goldset v0 annotations + run artifacts.

Tasks:
* ``header_mapping``: header paths + sample rows -> column roles/properties.
* ``row_record``: header paths + mapping + one row -> gold record.
* ``clause_extract``: clause title/text -> gold clause fields.
* ``row_record_perturb``: surface-only OCR noise (digit space, full width,
  footnote letter, header alias) over a row sample; the gold output is unchanged.
* ``citation_constraint``: reference + document selection context -> whether the
  citation is expanded and why.

Splits follow the goldset manifest (``mini``->train, ``dev``->dev,
``heldout``->heldout) and are document-level. The builder refuses to write
samples when a document leaks into two splits. Perturbations are only generated
for train/dev so heldout stays clean.

Usage:
    python tools/build_m2_dataset.py
    python tools/build_m2_dataset.py --runs runs/m2_baseline --out data/m2/train-v1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.tablegrid.normalize import clean_text  # noqa: E402

SPLIT_MAP = {"mini": "train", "dev": "dev", "heldout": "heldout"}
IGNORE_ROLES = {"ignore"}
RELEVANCE_PRIORITY = {"schema": 0, "method": 1, "unknown": 2, "informative": 3}
NUMERIC_CELL_RE = re.compile(
    r"^[<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[~～-]\s*[<>≤≥]?\s*\d+(?:\.\d+)?)?$"
)
FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")
HEADER_ALIASES = {
    "Rm": "抗拉强度",
    "Rp0.2": "规定塑性延伸强度",
    "A": "断后伸长率",
    "Z": "断面收缩率",
    "KV2": "冲击吸收能量",
    "KU2": "冲击吸收能量",
    "HBW": "布氏硬度",
    "HB": "布氏硬度",
    "HRC": "洛氏硬度",
    "HV": "维氏硬度",
    "E": "弹性模量",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--goldset", default=str(ROOT / "goldset" / "v0"), help="goldset directory"
    )
    parser.add_argument(
        "--runs", default=str(ROOT / "runs" / "m2_baseline"), help="run root"
    )
    parser.add_argument(
        "--out", default=str(ROOT / "data" / "m2" / "train-v1"), help="output dir"
    )
    args = parser.parse_args()

    gold_dir = Path(args.goldset)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    documents = manifest.get("documents") or []
    splits = _build_splits(documents)
    leakage = _leakage_issues(splits)
    if leakage:
        print("leakage detected:", "; ".join(leakage), file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_root = Path(args.runs)
    buckets: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "heldout": []}
    skipped: list[dict[str, str]] = []
    stats: Counter[tuple[str, str]] = Counter()

    for entry in documents:
        doc_id = entry["doc_id"]
        split = SPLIT_MAP.get(entry.get("split") or "dev", "dev")
        annotation_path = gold_dir / entry.get("annotation_file", "")
        if not annotation_path.exists():
            skipped.append({"doc_id": doc_id, "reason": "annotation_missing"})
            continue
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        run_dir = run_root / doc_id
        if not (run_dir / "tablegrid").exists():
            skipped.append({"doc_id": doc_id, "reason": "run_missing"})
            continue
        for table in annotation.get("tables") or []:
            samples, reasons = _table_samples(table, run_dir, doc_id, split)
            for reason in reasons:
                skipped.append({"doc_id": doc_id, "table_id": table.get("table_id", ""), "reason": reason})
            for sample in samples:
                buckets[split].append(sample)
                stats[(sample["task"], split)] += 1
                if sample["task"] == "row_record":
                    for extra in _perturb_samples(sample, split):
                        buckets[split].append(extra)
                        stats[(extra["task"], split)] += 1
        for clause in annotation.get("clauses") or []:
            sample = _clause_sample(clause, doc_id, split)
            if sample is None:
                skipped.append({"doc_id": doc_id, "clause_id": clause.get("clause_id", ""), "reason": "clause_empty"})
            else:
                buckets[split].append(sample)
                stats[(sample["task"], split)] += 1
        for sample in _citation_samples(run_dir, doc_id, split):
            buckets[split].append(sample)
            stats[(sample["task"], split)] += 1

    for split, rows in buckets.items():
        _write_jsonl(out_dir / f"{split}.jsonl", rows)
    (out_dir / "splits.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "goldset": str(gold_dir),
        "runs": str(run_root),
        "documents": len(documents),
        "splits": {split: len(rows) for split, rows in splits.items()},
        "samples": {
            split: {task: count for (task, s), count in stats.items() if s == split}
            for split in buckets
        },
        "skipped": skipped,
        "leakage": leakage,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["samples"], ensure_ascii=False))
    print(f"skipped {len(skipped)}; out={out_dir}")
    return 0


def _build_splits(documents: list[dict[str, Any]]) -> dict[str, list[str]]:
    splits: dict[str, list[str]] = defaultdict(list)
    for entry in documents:
        split = SPLIT_MAP.get(entry.get("split") or "dev", "dev")
        splits[split].append(entry["doc_id"])
    return {name: sorted(splits.get(name, [])) for name in ("train", "dev", "heldout")}


def _leakage_issues(splits: dict[str, list[str]]) -> list[str]:
    seen: dict[str, str] = {}
    issues: list[str] = []
    for split, docs in splits.items():
        for doc_id in docs:
            if doc_id in seen:
                issues.append(f"{doc_id} in {seen[doc_id]} and {split}")
            seen[doc_id] = split
    return issues


def _table_samples(
    table: dict[str, Any],
    run_dir: Path,
    doc_id: str,
    split: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    records = table.get("records") or []
    table_id = table.get("table_id")
    if not records or not table_id:
        return [], []
    path = run_dir / "tablegrid" / f"{table_id}.json"
    if not path.exists():
        return [], ["table_missing"]
    source = json.loads(path.read_text(encoding="utf-8"))
    rows = source.get("rows") or []
    header_paths = source.get("header_paths") or []
    header_rows = int(source.get("header_rows") or 0)
    mapping, mapping_error = _derive_mapping(rows, records)
    if mapping_error:
        return [], [mapping_error]
    columns = [
        {"index": index, **entry} for index, entry in sorted(mapping.items())
    ]
    samples: list[dict[str, Any]] = [
        {
            "task": "header_mapping",
            "doc_id": doc_id,
            "table_id": table_id,
            "profile": table.get("profile"),
            "input": {
                "header_paths": header_paths,
                "sample_rows": rows[header_rows : header_rows + 3],
            },
            "output": {"columns": columns},
            "meta": {"split": split, "source": "goldset-v0"},
        }
    ]
    for record in records:
        row_index = _record_row(record)
        if row_index is None or row_index >= len(rows):
            continue
        samples.append(
            {
                "task": "row_record",
                "doc_id": doc_id,
                "table_id": table_id,
                "profile": table.get("profile"),
                "input": {
                    "header_paths": header_paths,
                    "mapping": {"columns": columns},
                    "row": rows[row_index],
                },
                "output": _record_output(record),
                "meta": {"split": split, "source": "goldset-v0", "row_index": row_index},
            }
        )
    return samples, []


def _derive_mapping(
    rows: list[list[str]], records: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], str | None]:
    mapping: dict[int, dict[str, Any]] = {}
    for record in records:
        row_index = _record_row(record)
        if row_index is None or row_index >= len(rows):
            continue
        row = rows[row_index]
        property_entries = [
            (int(value["evidence"]["col"]), name, value)
            for name, value in (record.get("properties") or {}).items()
            if isinstance(value, dict) and isinstance(value.get("evidence"), dict)
            and value["evidence"].get("col") is not None
        ]
        property_cols = {col: (name, value) for col, name, value in property_entries}
        if len(property_cols) != len(property_entries):
            return {}, "mapping_conflict:same_col"
        for col, name, value in property_entries:
            if col >= len(row) or not clean_text(row[col]):
                return {}, f"property_cell_empty:{name}"
            previous = mapping.get(col)
            if previous and previous.get("property") != name:
                return {}, f"mapping_conflict:c{col}"
            mapping[col] = {
                "role": "property",
                "property": name,
                "unit": value.get("unit"),
            }
        grade_col = _find_cell(row, record.get("grade"), exclude=property_cols)
        if grade_col is not None:
            mapping.setdefault(grade_col, {"role": "grade"})
        for value in (record.get("facets") or {}).values():
            col = _find_cell(row, value, exclude=property_cols)
            if col is not None and col not in mapping:
                mapping[col] = {"role": "condition"}
        for part in str(record.get("condition") or "").split("/"):
            part = part.strip()
            if not part:
                continue
            col = _find_cell(row, part, exclude=property_cols)
            if col is not None and col not in mapping:
                mapping[col] = {"role": "condition"}
    if not any(entry["role"] == "property" for entry in mapping.values()):
        return {}, "no_property_columns"
    return mapping, None


def _find_cell(
    row: list[str],
    value: Any,
    *,
    exclude: dict[int, Any] | None = None,
) -> int | None:
    text = clean_text(value) if value is not None else ""
    if not text:
        return None
    exclude = exclude or {}
    for index, cell in enumerate(row):
        if index in exclude:
            continue
        cell_text = clean_text(cell)
        if cell_text and (cell_text == text or text in cell_text):
            return index
    return None


def _record_row(record: dict[str, Any]) -> int | None:
    for value in (record.get("properties") or {}).values():
        evidence = value.get("evidence") if isinstance(value, dict) else None
        if isinstance(evidence, dict) and evidence.get("row") is not None:
            return int(evidence["row"])
    return None


def _record_output(record: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    for name, value in (record.get("properties") or {}).items():
        if not isinstance(value, dict):
            continue
        properties[name] = {
            "raw": value.get("raw"),
            "comparator": value.get("comparator"),
            "unit": value.get("unit"),
        }
    return {
        "grade": record.get("grade"),
        "condition": record.get("condition"),
        "properties": properties,
    }


def _clause_sample(
    clause: dict[str, Any], doc_id: str, split: str
) -> dict[str, Any] | None:
    fields = clause.get("fields") or {}
    if not fields:
        return None
    title = clean_text(clause.get("title"))
    quotes: list[str] = []
    for value in fields.values():
        evidence = value.get("evidence") if isinstance(value, dict) else None
        quote = clean_text(evidence.get("quote")) if isinstance(evidence, dict) else ""
        if quote and quote not in quotes:
            quotes.append(quote)
    text = " ".join([title, *quotes]) if quotes else title
    return {
        "task": "clause_extract",
        "doc_id": doc_id,
        "clause_id": clause.get("clause_id"),
        "input": {
            "title": title,
            "text": text,
            "kind": clause.get("kind"),
            "quotes": quotes,
        },
        "output": {
            "fields": {
                name: {
                    "raw": value.get("raw") if isinstance(value, dict) else None,
                    "text": value.get("text") if isinstance(value, dict) else None,
                    "comparator": value.get("comparator") if isinstance(value, dict) else None,
                    "unit": value.get("unit") if isinstance(value, dict) else None,
                }
                for name, value in fields.items()
            }
        },
        "meta": {"split": split, "source": "goldset-v0"},
    }


def _perturb_samples(
    sample: dict[str, Any], split: str
) -> list[dict[str, Any]]:
    """Return surface-only variants of one row_record sample."""
    if split == "heldout":
        return []
    mapping = {
        int(entry["index"]): entry
        for entry in sample["input"].get("mapping", {}).get("columns", [])
    }
    row = list(sample["input"].get("row") or [])
    headers = [list(path) for path in sample["input"].get("header_paths") or []]
    variants: list[dict[str, Any]] = []

    numeric_cols = [
        col
        for col, entry in mapping.items()
        if entry.get("role") == "property"
        and col < len(row)
        and _matches_gold_cell(
            row[col],
            (sample["output"].get("properties") or {}).get(entry.get("property")),
        )
        and NUMERIC_CELL_RE.match(clean_text(row[col]))
        and sum(char.isdigit() for char in clean_text(row[col])) >= 2
    ]
    if numeric_cols:
        col = numeric_cols[0]
        cell = clean_text(row[col])
        fullwidth = (int(sample.get("meta", {}).get("row_index") or 0) % 2) == 1
        changed = cell.translate(FULLWIDTH_DIGITS) if fullwidth else re.sub(
            r"(\d)(?=\d)", r"\1 ", cell, count=1
        )
        new_row = list(row)
        new_row[col] = changed
        variants.append(
            _variant(
                sample,
                new_row,
                headers,
                [{"kind": "fullwidth" if fullwidth else "digit_space", "col": col, "from": cell, "to": changed}],
            )
        )

    grade = clean_text(sample["output"].get("grade"))
    surface_added = False
    if grade and not grade[-1].islower():
        for col, entry in mapping.items():
            if (
                entry.get("role") == "grade"
                and col < len(row)
                and clean_text(row[col]) == grade
            ):
                new_row = list(row)
                new_row[col] = f"{grade}a"
                variants.append(
                    _variant(
                        sample,
                        new_row,
                        headers,
                        [{"kind": "grade_footnote", "col": col, "from": grade, "to": f"{grade}a"}],
                    )
                )
                surface_added = True
                break
    if not surface_added:
        for col, entry in mapping.items():
            symbol = entry.get("property")
            alias = HEADER_ALIASES.get(symbol or "")
            if entry.get("role") != "property" or not alias or col >= len(headers):
                continue
            path = headers[col]
            leaf = path[-1] if path else ""
            if symbol not in leaf:
                continue
            new_leaf = leaf.replace(symbol, alias, 1)
            new_headers = [list(item) for item in headers]
            new_headers[col] = path[:-1] + [new_leaf]
            variants.append(
                _variant(
                    sample,
                    row,
                    new_headers,
                    [{"kind": "header_alias", "col": col, "from": leaf, "to": new_leaf}],
                )
            )
            break
    return variants


def _matches_gold_cell(cell: Any, gold: Any) -> bool:
    if not isinstance(gold, dict):
        return False
    left = clean_text(cell)
    right = clean_text(gold.get("raw"))
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _variant(
    sample: dict[str, Any],
    row: list[str],
    headers: list[list[str]],
    ops: list[dict[str, Any]],
) -> dict[str, Any]:
    meta = dict(sample.get("meta") or {})
    meta.update({"source_task": "row_record", "ops": ops})
    return {
        **sample,
        "task": "row_record_perturb",
        "input": {**sample["input"], "row": row, "header_paths": headers},
        "meta": meta,
    }


def _citation_samples(
    run_dir: Path, doc_id: str, split: str
) -> list[dict[str, Any]]:
    """Per-reference expansion decision with replayable selection context."""
    path = run_dir / "references.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    references = payload.get("references") or []
    budget = int((payload.get("budget") or {}).get("max_documents") or 8)
    ordered = sorted(
        references,
        key=lambda edge: (
            RELEVANCE_PRIORITY.get(edge.get("relevance") or "unknown", 9),
            0 if edge.get("relation") == "normative" else 1,
            edge.get("standard_no") or "",
        ),
    )
    selected: set[str] = set()
    samples: list[dict[str, Any]] = []
    for rank, edge in enumerate(ordered, start=1):
        key = edge.get("standard_no") or edge.get("raw") or ""
        duplicate = key in selected
        samples.append(
            {
                "task": "citation_constraint",
                "doc_id": doc_id,
                "clause_id": edge.get("clause_id"),
                "input": {
                    "raw": edge.get("raw"),
                    "standard_no": key,
                    "title": edge.get("title"),
                    "relation": edge.get("relation"),
                    "dated": bool(edge.get("dated")),
                    "superseded_by": edge.get("superseded_by"),
                    "relevance": edge.get("relevance"),
                    "context": {
                        "budget": budget,
                        "rank": rank,
                        "selected_before": len(selected),
                        "duplicate": duplicate,
                    },
                },
                "output": {
                    "expand": bool(edge.get("expand")),
                    "selection_reason": edge.get("selection_reason"),
                },
                "meta": {"split": split, "source": "references.json"},
            }
        )
        if edge.get("relevance") != "informative" and not duplicate and len(selected) < budget:
            selected.add(key)
    return samples


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
