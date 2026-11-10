"""M2.3-05 stability check: fixed inference params, repeated runs.

Reuses the parameters in ``inference_params.json`` (greedy, no thinking,
max_new_tokens 512) and generates the same sample several times to verify:
* identical output across repeats (greedy determinism)
* JSON validity on every repeat
* no output hits the token cap (truncation would silently cut JSON)

Usage on the model host:
    python eval_stability.py --model ... --adapter ... \
      --data /home/grainuser/hanson_m2/data/heldout.jsonl \
      --params /home/grainuser/hanson_m2/code/inference_params.json \
      --out /home/grainuser/hanson_m2/eval/stability.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from eval_heldout import extract_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--per-task", type=int, default=1)
    parser.add_argument("--extra", type=int, default=1)
    return parser.parse_args()


def pick_samples(rows: list[dict[str, Any]], per_task: int, extra: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("task") not in ("header_mapping", "row_record", "clause_extract", "citation_constraint"):
            continue
        task = row["task"]
        if counts.get(task, 0) < per_task:
            chosen.append(row)
            counts[task] = counts.get(task, 0) + 1
    for row in rows:
        if len(chosen) >= sum(counts.values()) + extra:
            break
        if row not in chosen and row.get("task") in counts:
            chosen.append(row)
    return chosen


def build_prompt(tokenizer: Any, row: dict[str, Any], enable_thinking: bool) -> str:
    from eval_two_stage import SYSTEM

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": row["_instruction"]},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=enable_thinking
    )


def main() -> int:
    args = parse_args()
    params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    if params.get("do_sample"):
        raise SystemExit("stability check expects do_sample=false")

    from eval_two_stage import INSTRUCTIONS, user_content

    rows = [
        json.loads(line)
        for line in Path(args.data).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    samples = pick_samples(rows, args.per_task, args.extra)
    for row in samples:
        instruction = INSTRUCTIONS.get(row["task"])
        if instruction is None:
            raise SystemExit(f"unknown task {row['task']}")
        row["_instruction"] = user_content(instruction, row["input"])

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True
    ).to("cuda")
    model.config.use_cache = True
    model.eval()

    from peft import PeftModel

    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    started = time.time()
    results = []
    for row in samples:
        prompt = build_prompt(tokenizer, row, params["enable_thinking"])
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        runs = []
        for _ in range(args.repeats):
            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=params["max_new_tokens"],
                    do_sample=False,
                    repetition_penalty=params["repetition_penalty"],
                )
            generated = output[0][inputs["input_ids"].shape[1] :]
            text = tokenizer.decode(generated, skip_special_tokens=True)
            runs.append(
                {
                    "tokens": int(generated.shape[0]),
                    "truncated": int(generated.shape[0]) >= params["max_new_tokens"],
                    "json_valid": extract_json(text) is not None,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "head": text.strip()[:120],
                }
            )
        results.append(
            {
                "task": row["task"],
                "doc_id": row.get("doc_id"),
                "table_id": row.get("table_id"),
                "runs": runs,
                "distinct_outputs": len({run["sha256"] for run in runs}),
            }
        )
        print(
            f"[stability] {row['task']} distinct={results[-1]['distinct_outputs']} "
            f"tokens={[run['tokens'] for run in runs]}",
            flush=True,
        )

    total = sum(len(item["runs"]) for item in results)
    all_valid = sum(1 for item in results for run in item["runs"] if run["json_valid"])
    truncated = sum(1 for item in results for run in item["runs"] if run["truncated"])
    deterministic = all(item["distinct_outputs"] == 1 for item in results)
    summary = {
        "samples": len(results),
        "repeats": args.repeats,
        "generations": total,
        "deterministic": deterministic,
        "json_valid": round(all_valid / total, 4) if total else 0.0,
        "truncated": truncated,
        "max_tokens_used": max(
            (run["tokens"] for item in results for run in item["runs"]), default=0
        ),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    report = {"params": params, "summary": summary, "results": results}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
