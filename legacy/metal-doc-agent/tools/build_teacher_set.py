"""Build the M2.2 teacher set (teacher = the current agent model).

Two modes:

* ``emit``: rank dev documents by evaluation errors, pick hard-case samples
  (header_mapping / row_record / clause_extract), and write teacher inputs
  without gold outputs.
* ``validate``: read teacher outputs, apply L0/L1 evidence filters, compare to
  gold, and write ``teacher-v1`` plus an agreement report.

Usage:
    python tools/build_teacher_set.py emit
    python tools/build_teacher_set.py validate --raw data/m2/teacher-v1/teacher_raw.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.tablegrid.normalize import clean_text  # noqa: E402

TASKS = ("header_mapping", "row_record", "clause_extract")
TASK_ORDER = {task: index for index, task in enumerate(TASKS)}


def emit(
    eval_path: Path,
    dataset_dir: Path,
    out_dir: Path,
    *,
    documents: int = 5,
) -> dict[str, Any]:
    evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
    split_docs = _dev_docs(dataset_dir)
    ranked = sorted(
        (
            (len(doc.get("errors") or []), doc["doc_id"])
            for doc in evaluation.get("documents") or []
            if doc["doc_id"] in split_docs
        ),
        reverse=True,
    )
    selected_docs = [doc_id for _, doc_id in ranked[:documents]]
    rows = _load_jsonl(dataset_dir / "dev.jsonl")
    inputs: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for doc_id in selected_docs:
        errors = next(
            (
                len(doc.get("errors") or [])
                for doc in evaluation["documents"]
                if doc["doc_id"] == doc_id
            ),
            0,
        )
        for task in TASKS:
            sample = next(
                (
                    row
                    for row in rows
                    if row["doc_id"] == doc_id and row["task"] == task
                ),
                None,
            )
            if sample is None:
                continue
            sample_id = f"{doc_id}:{task}"
            item = {
                "id": sample_id,
                "task": task,
                "doc_id": doc_id,
                "table_id": sample.get("table_id"),
                "clause_id": sample.get("clause_id"),
                "hard_reason": f"{errors} errors in evaluation",
                "input": sample["input"],
            }
            inputs.append(item)
            gold.append(
                {
                    "id": sample_id,
                    "task": task,
                    "doc_id": doc_id,
                    "table_id": sample.get("table_id"),
                    "clause_id": sample.get("clause_id"),
                    "input": sample["input"],
                    "output": sample["output"],
                    "meta": sample.get("meta") or {},
                }
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "teacher_inputs.jsonl", inputs)
    _write_jsonl(out_dir / "teacher_gold.jsonl", gold)
    print(f"docs={selected_docs} inputs={len(inputs)} out={out_dir}")
    return {"documents": selected_docs, "inputs": len(inputs)}


def validate(
    raw_path: Path, dataset_dir: Path, out_dir: Path
) -> dict[str, Any]:
    gold_rows = {
        row["id"]: row
        for row in _load_jsonl(out_dir / "teacher_gold.jsonl")
    }
    raw_rows = _load_jsonl(raw_path)
    accepted: list[dict[str, Any]] = []
    rejected = 0
    dropped_values = 0
    matches = 0
    field_total = 0
    field_ok = 0
    by_task: dict[str, dict[str, int]] = {}
    for raw in raw_rows:
        sample_id = raw.get("id")
        gold = gold_rows.get(sample_id)
        if gold is None:
            rejected += 1
            continue
        cleaned, dropped = _apply_l0(raw, gold)
        dropped_values += dropped
        if cleaned is None:
            rejected += 1
            continue
        task_ok, task_total = _compare(cleaned["output"], gold["output"], gold["task"])
        if task_ok == task_total and task_total > 0:
            matches += 1
        field_ok += task_ok
        field_total += task_total
        stats = by_task.setdefault(
            gold["task"], {"samples": 0, "exact": 0, "fields": 0, "ok": 0}
        )
        stats["samples"] += 1
        stats["fields"] += task_total
        stats["ok"] += task_ok
        if task_ok == task_total and task_total > 0:
            stats["exact"] += 1
        accepted.append(
            {
                "id": sample_id,
                "task": gold["task"],
                "doc_id": gold["doc_id"],
                "table_id": gold.get("table_id"),
                "clause_id": gold.get("clause_id"),
                "input": gold["input"],
                "teacher_output": cleaned["output"],
                "gold_output": gold["output"],
                "status": "accepted",
            }
        )
    for stats in by_task.values():
        stats["field_accuracy"] = (
            round(stats["ok"] / stats["fields"], 4) if stats["fields"] else 0.0
        )
    report = {
        "teacher": "current agent model (offline, no external endpoint)",
        "inputs": len(gold_rows),
        "teacher_outputs": len(raw_rows),
        "accepted": len(accepted),
        "rejected": rejected,
        "dropped_values_l0": dropped_values,
        "exact_match": matches,
        "exact_match_rate": round(matches / len(accepted), 4) if accepted else 0.0,
        "field_accuracy": round(field_ok / field_total, 4) if field_total else 0.0,
        "by_task": dict(by_task),
        "mix": {
            "policy": "gold first; teacher only for hard cases",
            "teacher_share": round(len(accepted) / 802, 4) if accepted else 0.0,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "teacher.jsonl", accepted)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _apply_l0(
    raw: dict[str, Any], gold: dict[str, Any]
) -> tuple[dict[str, Any] | None, int]:
    task = gold["task"]
    output = raw.get("output")
    if not isinstance(output, dict):
        return None, 0
    if task == "header_mapping":
        columns = output.get("columns")
        if not isinstance(columns, list):
            return None, 0
        paths = gold.get("input", {}).get("header_paths") or []
        cleaned = []
        for column in columns:
            try:
                index = int(column.get("index"))
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(paths):
                continue
            if column.get("role") == "property" and not column.get("property"):
                continue
            cleaned.append(column)
        if not cleaned:
            return None, len(columns)
        return {**raw, "output": {"columns": cleaned}}, len(columns) - len(cleaned)
    if task == "row_record":
        row = gold.get("input", {}).get("row") or []
        cells = [clean_text(cell) for cell in row]
        properties = {}
        dropped = 0
        for name, value in (output.get("properties") or {}).items():
            raw_value = clean_text(value.get("raw") if isinstance(value, dict) else None)
            if not raw_value or not any(
                raw_value == cell or raw_value in cell for cell in cells if cell
            ):
                dropped += 1
                continue
            properties[name] = value
        if not properties:
            return None, dropped
        return {
            **raw,
            "output": {
                "grade": output.get("grade"),
                "condition": output.get("condition"),
                "properties": properties,
            },
        }, dropped
    if task == "clause_extract":
        text = clean_text(gold.get("input", {}).get("text"))
        fields = {}
        dropped = 0
        for name, value in (output.get("fields") or {}).items():
            raw_value = clean_text(
                (value.get("raw") or value.get("text"))
                if isinstance(value, dict)
                else None
            )
            if not raw_value or raw_value not in text:
                dropped += 1
                continue
            fields[name] = value
        if not fields:
            return None, dropped
        return {**raw, "output": {"fields": fields}}, dropped
    return None, 0


def _compare(teacher: dict[str, Any], gold: dict[str, Any], task: str) -> tuple[int, int]:
    if task == "header_mapping":
        gold_cols = {
            int(item["index"]): item for item in gold.get("columns") or []
        }
        ok = 0
        for item in teacher.get("columns") or []:
            target = gold_cols.get(int(item.get("index", -1)))
            if target is None:
                continue
            if (
                item.get("role") == target.get("role")
                and item.get("property") == target.get("property")
            ):
                ok += 1
        return ok, len(gold_cols)
    if task == "row_record":
        total = 2 + len(gold.get("properties") or {})
        ok = int(teacher.get("grade") == gold.get("grade")) + int(
            teacher.get("condition") == gold.get("condition")
        )
        for name, expected in (gold.get("properties") or {}).items():
            actual = (teacher.get("properties") or {}).get(name)
            if isinstance(actual, dict) and clean_text(
                actual.get("raw")
            ) == clean_text(expected.get("raw")):
                ok += 1
        return ok, total
    if task == "clause_extract":
        gold_fields = gold.get("fields") or {}
        ok = 0
        for name, expected in gold_fields.items():
            actual = (teacher.get("fields") or {}).get(name)
            if isinstance(actual, dict) and clean_text(
                actual.get("raw") or actual.get("text")
            ) == clean_text(expected.get("raw") or expected.get("text")):
                ok += 1
        return ok, len(gold_fields)
    return 0, 0


def _dev_docs(dataset_dir: Path) -> set[str]:
    rows = _load_jsonl(dataset_dir / "dev.jsonl")
    return {row["doc_id"] for row in rows}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument(
        "--eval", default=str(ROOT / "eval" / "m2_baseline" / "eval.json")
    )
    emit_parser.add_argument("--dataset", default=str(ROOT / "data" / "m2" / "train-v1"))
    emit_parser.add_argument("--out", default=str(ROOT / "data" / "m2" / "teacher-v1"))
    emit_parser.add_argument("--documents", type=int, default=5)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--raw", required=True)
    validate_parser.add_argument(
        "--dataset", default=str(ROOT / "data" / "m2" / "train-v1")
    )
    validate_parser.add_argument("--out", default=str(ROOT / "data" / "m2" / "teacher-v1"))
    args = parser.parse_args(argv)
    if args.command == "emit":
        emit(Path(args.eval), Path(args.dataset), Path(args.out), documents=args.documents)
        return 0
    validate(Path(args.raw), Path(args.dataset), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
