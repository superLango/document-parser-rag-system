"""Two-stage extraction: header_mapping -> row_record, using the LoRA adapter.

Stage 1 predicts the column mapping from ``header_paths`` + sample rows; stage 2
feeds that *predicted* mapping (not the gold mapping) into per-row extraction.
This measures error propagation, which the single-stage heldout run hides
because its inputs already carry the gold mapping.

Also supports a long-table stability pass against a real ``tablegrid`` artifact:
one mapping, N rows, checking row coverage / JSON validity / property-key
consistency instead of gold accuracy (long tables are unannotated).

Prompt strings must match ``metal-doc-agent/tools/prepare_sft.py`` so the
request stays in the SFT distribution.

Usage on the model host:
    python eval_two_stage.py --model ... --adapter ... \
      --data /home/grainuser/hanson_m2/data/heldout.jsonl \
      --out /home/grainuser/hanson_m2/eval/two-stage.json

    python eval_two_stage.py --model ... --adapter ... \
      --table /home/grainuser/hanson_m2/data/table-t8.json --table-rows 41 \
      --out /home/grainuser/hanson_m2/eval/longtable.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from eval_heldout import compare, extract_json, flatten

SYSTEM = (
    "你是金属材料标准结构化抽取器。只能使用输入中出现的文字、数值和标准编号，"
    "不得推断、补全或改写数值；不确定的字段不要输出。只输出 JSON，不要解释。"
)

INSTRUCTIONS = {
    "header_mapping": (
        "任务：header_mapping。为每一列给出 role（grade/condition/property/ignore）；"
        "property 使用输入中出现的属性名或标准属性符号，unit 可为空。"
    ),
    "row_record": (
        "任务：row_record。输出 grade、condition、properties；每个属性包含 raw、"
        "comparator、unit，raw 必须逐字来自 row。"
    ),
    "clause_extract": (
        "任务：clause_extract。输出 fields；每个字段包含 raw、text、comparator、unit，"
        "raw 必须逐字出现在 text 中。"
    ),
    "citation_constraint": (
        "任务：citation_constraint。根据引用属性与选择上下文判断是否展开，"
        "输出 expand 与 selection_reason。"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--data", default=None)
    parser.add_argument("--table", default=None)
    parser.add_argument("--table-rows", type=int, default=40)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--limit-tables", type=int, default=0)
    return parser.parse_args()


def generate(model: Any, tokenizer: Any, user_content: str, max_new_tokens: int) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_content},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False
        )
    return tokenizer.decode(
        output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )


def user_content(instruction: str, payload: dict[str, Any]) -> str:
    return instruction + "\n输入：" + json.dumps(payload, ensure_ascii=False)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def mapping_accuracy(pred: Any, gold: Any) -> dict[str, Any]:
    gold_cols = {col.get("index"): col for col in (gold or {}).get("columns", [])}
    pred_cols = {col.get("index"): col for col in (pred or {}).get("columns", [])}
    indexes = sorted(set(gold_cols) | set(pred_cols))
    role_ok = full_ok = 0
    for index in indexes:
        gold_col = gold_cols.get(index, {})
        pred_col = pred_cols.get(index, {})
        role_match = _norm(pred_col.get("role")) == _norm(gold_col.get("role"))
        full_match = (
            role_match
            and _norm(pred_col.get("property")) == _norm(gold_col.get("property"))
            and _norm(pred_col.get("unit")) == _norm(gold_col.get("unit"))
        )
        role_ok += int(role_match)
        full_ok += int(full_match)
    total = len(indexes) or 1
    return {
        "columns": len(indexes),
        "role_accuracy": round(role_ok / total, 4),
        "full_accuracy": round(full_ok / total, 4),
    }


def run_heldout(model: Any, tokenizer: Any, rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    tables: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if row.get("task") not in ("header_mapping", "row_record"):
            continue
        key = (row["doc_id"], row.get("table_id") or "")
        tables.setdefault(key, {"header": None, "rows": []})
        row["_id"] = f"{row['doc_id']}:{row['task']}:{index}"
        if row["task"] == "header_mapping":
            tables[key]["header"] = row
        else:
            tables[key]["rows"].append(row)

    keys = [key for key, value in tables.items() if value["header"] and value["rows"]]
    if args.limit_tables:
        keys = keys[: args.limit_tables]

    report: list[dict[str, Any]] = []
    for doc_id, table_id in keys:
        entry = tables[(doc_id, table_id)]
        header_row = entry["header"]
        started = time.time()
        text = generate(
            model,
            tokenizer,
            user_content(INSTRUCTIONS["header_mapping"], header_row["input"]),
            args.max_new_tokens,
        )
        mapping = extract_json(text)
        gold_mapping = header_row["output"]
        table_report: dict[str, Any] = {
            "doc_id": doc_id,
            "table_id": table_id,
            "mapping_valid": mapping is not None,
            "mapping": mapping_accuracy(mapping, gold_mapping),
            "rows": [],
        }
        for row in entry["rows"]:
            gold = row["output"]
            if mapping is None:
                table_report["rows"].append(
                    {"id": row["_id"], "json_valid": False, "exact": False, "f1": 0.0}
                )
                continue
            payload = dict(row["input"])
            payload["mapping"] = mapping
            row_text = generate(
                model,
                tokenizer,
                user_content(INSTRUCTIONS["row_record"], payload),
                args.max_new_tokens,
            )
            pred = extract_json(row_text)
            item: dict[str, Any] = {
                "id": row["_id"],
                "json_valid": pred is not None,
                "exact": pred == gold,
                "output_head": row_text.strip()[:200],
            }
            if pred is not None:
                item.update(compare(pred, gold))
            else:
                item.update({"precision": 0.0, "recall": 0.0, "f1": 0.0})
            table_report["rows"].append(item)
        table_report["elapsed_seconds"] = round(time.time() - started, 1)
        report.append(table_report)
        print(
            f"[table] {doc_id}|{table_id} mapping_full={table_report['mapping']['full_accuracy']} "
            f"rows={len(table_report['rows'])}",
            flush=True,
        )

    total_rows = sum(len(table["rows"]) for table in report)
    valid = sum(1 for table in report for row in table["rows"] if row["json_valid"])
    exact = sum(1 for table in report for row in table["rows"] if row["exact"])
    f1 = (
        sum(row.get("f1", 0.0) for table in report for row in table["rows"]) / total_rows
        if total_rows
        else 0.0
    )
    mapping_full = (
        sum(table["mapping"]["full_accuracy"] for table in report) / len(report)
        if report
        else 0.0
    )
    summary = {
        "tables": len(report),
        "rows": total_rows,
        "mapping_full_accuracy": round(mapping_full, 4),
        "json_valid": round(valid / total_rows, 4) if total_rows else 0.0,
        "exact": round(exact / total_rows, 4) if total_rows else 0.0,
        "row_f1": round(f1, 4),
    }
    return {"summary": summary, "tables": report}


def run_long_table(model: Any, tokenizer: Any, args: argparse.Namespace) -> dict[str, Any]:
    table = json.loads(Path(args.table).read_text(encoding="utf-8"))
    header_paths = table["header_paths"]
    rows = table["rows"]
    header_rows = int(table.get("header_rows") or 0)
    data_rows = rows[header_rows:][: args.table_rows]

    started = time.time()
    text = generate(
        model,
        tokenizer,
        user_content(
            INSTRUCTIONS["header_mapping"],
            {"header_paths": header_paths, "sample_rows": data_rows[:2]},
        ),
        args.max_new_tokens,
    )
    mapping = extract_json(text)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(data_rows):
        if mapping is None:
            failures.append({"index": index, "reason": "mapping_invalid"})
            continue
        row_text = generate(
            model,
            tokenizer,
            user_content(
                INSTRUCTIONS["row_record"],
                {"header_paths": header_paths, "mapping": mapping, "row": row},
            ),
            args.max_new_tokens,
        )
        pred = extract_json(row_text)
        if pred is None:
            failures.append({"index": index, "reason": "json_invalid", "head": row_text[:120]})
            continue
        records.append({"index": index, "record": pred})

    key_sets = [tuple(sorted(flatten(record["record"].get("properties", {})))) for record in records]
    stable_keys = len(set(key_sets)) == 1 if key_sets else False
    grades = [record["record"].get("grade") for record in records]
    duplicates = len(grades) - len(set(grades)) if grades else 0
    empty = sum(1 for record in records if not record["record"].get("properties"))
    return {
        "table": args.table,
        "caption": table.get("caption"),
        "rows_in": len(data_rows),
        "rows_out": len(records),
        "json_valid": round(len(records) / len(data_rows), 4) if data_rows else 0.0,
        "mapping_valid": mapping is not None,
        "mapping_columns": len((mapping or {}).get("columns", [])),
        "stable_property_keys": stable_keys,
        "distinct_key_sets": len(set(key_sets)),
        "empty_properties": empty,
        "duplicate_grades": duplicates,
        "failures": failures,
        "elapsed_seconds": round(time.time() - started, 1),
        "records": records,
    }


def main() -> int:
    args = parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True
    ).to("cuda")
    model.config.use_cache = True
    model.eval()

    from peft import PeftModel

    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    report: dict[str, Any] = {"model": args.model, "adapter": args.adapter, "thinking": False}
    if args.table:
        report["long_table"] = run_long_table(model, tokenizer, args)
    if args.data:
        rows = [
            json.loads(line)
            for line in Path(args.data).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report["two_stage"] = run_heldout(model, tokenizer, rows, args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if "long_table" in report:
        table = report["long_table"]
        print(
            f"long_table rows {table['rows_out']}/{table['rows_in']} "
            f"valid={table['json_valid']} stable_keys={table['stable_property_keys']} "
            f"keysets={table['distinct_key_sets']} dup={table['duplicate_grades']}"
        )
    if "two_stage" in report:
        print("two_stage", json.dumps(report["two_stage"]["summary"], ensure_ascii=False))
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
