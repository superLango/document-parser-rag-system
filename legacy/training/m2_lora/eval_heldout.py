"""Evaluate base vs LoRA adapter on the M2 heldout SFT samples.

Greedy decoding, ``enable_thinking=False`` (the adapter requires it: with
thinking enabled Qwen3.5 emits a reasoning trace instead of JSON).

Metrics per task and overall:
* ``json_valid``: first JSON object found in the output parses
* ``exact``: parsed output deep-equals the gold JSON
* ``precision/recall/f1``: leaf ``path=value`` comparison against gold
* ``unsupported``: leaf ``*.raw`` values that do not appear verbatim in the user
  input (crude hallucination proxy, counted, not judged)

``--guided`` forces the output through a per-task JSON schema (lm-format-enforcer
prefix masking), which is the M2.3-02 acceptance path (illegal JSON = 0).

Usage on the model host:
    python eval_heldout.py \
      --model /home/grainuser/models/models/Qwen3.5-9B \
      --adapter /home/grainuser/hanson_m2/adapter-v1 \
      --data /home/grainuser/hanson_m2/data/eval.jsonl \
      --out /home/grainuser/hanson_m2/eval/heldout-lora.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

GUIDED_SCHEMAS: dict[str, dict[str, Any]] = {
    "header_mapping": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "role": {"type": "string"},
                        "property": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["index", "role"],
                },
            }
        },
        "required": ["columns"],
    },
    "row_record": {
        "type": "object",
        "properties": {
            "grade": {"type": ["string", "null"]},
            "condition": {"type": ["string", "null"]},
            "properties": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": ["string", "number"]},
                        "comparator": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["raw"],
                },
            },
        },
        "required": ["properties"],
    },
    "clause_extract": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": ["string", "number"]},
                        "text": {"type": ["string", "null"]},
                        "comparator": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["raw"],
                },
            }
        },
        "required": ["fields"],
    },
    "citation_constraint": {
        "type": "object",
        "properties": {
            "expand": {"type": "boolean"},
            "selection_reason": {"type": "string"},
        },
        "required": ["expand"],
    },
}


def _patch_lmf_transformers() -> None:
    """lm-format-enforcer still imports ``PreTrainedTokenizerBase`` from the
    pre-5.x ``transformers.tokenization_utils`` path, which transformers 5.20
    no longer exposes. Register the class on that module before importing lmf.
    """
    import sys
    import types

    import transformers
    from transformers.tokenization_utils_base import PreTrainedTokenizerBase

    module = sys.modules.get("transformers.tokenization_utils")
    if module is None:
        module = types.ModuleType("transformers.tokenization_utils")
        sys.modules["transformers.tokenization_utils"] = module
        setattr(transformers, "tokenization_utils", module)
    if not hasattr(module, "PreTrainedTokenizerBase"):
        module.PreTrainedTokenizerBase = PreTrainedTokenizerBase


def build_prefix_fn(tokenizer: Any, tokenizer_data: Any, task: str) -> Any:
    _patch_lmf_transformers()
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.integrations.transformers import (
        build_transformers_prefix_allowed_tokens_fn,
    )

    key = "row_record" if task == "row_record_perturb" else task
    parser = JsonSchemaParser(GUIDED_SCHEMAS[key])
    return build_transformers_prefix_allowed_tokens_fn(tokenizer_data, parser)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-base", action="store_true")
    parser.add_argument("--guided", action="store_true")
    return parser.parse_args()


def extract_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text[start:])
            return value
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    return None


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(node, list):
        out = {}
        for index, value in enumerate(node):
            out.update(flatten(value, f"{prefix}[{index}]"))
        return out
    return {prefix: node}


def compare(pred: Any, gold: Any) -> dict[str, Any]:
    pred_flat = flatten(pred)
    gold_flat = flatten(gold)
    hit = sum(
        1
        for path, value in pred_flat.items()
        if path in gold_flat and _norm(gold_flat[path]) == _norm(value)
    )
    precision = hit / len(pred_flat) if pred_flat else 0.0
    recall = hit / len(gold_flat) if gold_flat else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "pred_leaves": len(pred_flat),
        "gold_leaves": len(gold_flat),
    }


def unsupported(pred: Any, haystack: str) -> int:
    """Count ``*.raw`` values that do not appear verbatim in the user input.

    Only ``raw`` leaves are evidence-bearing values (row cells / clause text);
    structural leaves (role, unit, property symbols) are not checked.
    """
    count = 0
    for path, value in flatten(pred).items():
        if not path.endswith(".raw"):
            continue
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if text and text not in haystack:
            count += 1
    return count


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value).strip()


def evaluate(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, Any]],
    label: str,
    max_new_tokens: int,
    tokenizer_data: Any = None,
) -> list[dict[str, Any]]:
    results = []
    started = time.time()
    for index, row in enumerate(rows, 1):
        messages = row["messages"]
        prompt = tokenizer.apply_chat_template(
            messages[:2],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        generate_kwargs: dict[str, Any] = {}
        if tokenizer_data is not None:
            generate_kwargs["prefix_allowed_tokens_fn"] = build_prefix_fn(
                tokenizer, tokenizer_data, row["task"]
            )
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                **generate_kwargs,
            )
        text = tokenizer.decode(
            output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )
        pred = extract_json(text)
        gold = json.loads(messages[2]["content"])
        entry: dict[str, Any] = {
            "id": row["id"],
            "task": row["task"],
            "json_valid": pred is not None,
            "exact": pred == gold,
            "output_head": text.strip()[:300],
        }
        if pred is not None:
            entry.update(compare(pred, gold))
            entry["unsupported"] = unsupported(pred, messages[1]["content"])
        results.append(entry)
        if index % 10 == 0 or index == len(rows):
            elapsed = time.time() - started
            print(
                f"[{label}] {index}/{len(rows)} {elapsed:.0f}s "
                f"({elapsed / index:.1f}s/sample)",
                flush=True,
            )
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        valid = sum(1 for row in rows if row["json_valid"])
        exact = sum(1 for row in rows if row["exact"])
        scored = [row for row in rows if row["json_valid"]]
        precision = sum(row["precision"] for row in scored) / len(scored) if scored else 0.0
        recall = sum(row["recall"] for row in scored) / len(scored) if scored else 0.0
        f1 = sum(row["f1"] for row in scored) / len(scored) if scored else 0.0
        unsupported_total = sum(row.get("unsupported", 0) for row in scored)
        leaves = sum(row["pred_leaves"] for row in scored)
        return {
            "samples": total,
            "json_valid": round(valid / total, 4) if total else 0.0,
            "exact": round(exact / total, 4) if total else 0.0,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "unsupported_rate": round(unsupported_total / leaves, 4) if leaves else 0.0,
        }

    summary: dict[str, Any] = {"overall": _agg(results)}
    tasks = sorted({row["task"] for row in results})
    summary["by_task"] = {
        task: _agg([row for row in results if row["task"] == task]) for task in tasks
    }
    return summary


def main() -> int:
    args = parse_args()
    rows = [
        json.loads(line)
        for line in Path(args.data).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        rows = rows[: args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True
    ).to("cuda")
    model.config.use_cache = True
    model.eval()

    report: dict[str, Any] = {
        "model": args.model,
        "adapter": args.adapter,
        "data": args.data,
        "samples": len(rows),
        "max_new_tokens": args.max_new_tokens,
        "thinking": False,
        "guided": args.guided,
    }
    tokenizer_data = None
    if args.guided:
        _patch_lmf_transformers()
        from lmformatenforcer.integrations.transformers import (
            build_token_enforcer_tokenizer_data,
        )

        tokenizer_data = build_token_enforcer_tokenizer_data(tokenizer)
    if not args.skip_base:
        base_results = evaluate(
            model, tokenizer, rows, "base", args.max_new_tokens, tokenizer_data
        )
        report["base"] = {
            "summary": summarize(base_results),
            "results": base_results,
        }

    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter)
        model.eval()
        adapter_results = evaluate(
            model, tokenizer, rows, "adapter", args.max_new_tokens, tokenizer_data
        )
        report["adapter"] = {
            "summary": summarize(adapter_results),
            "results": adapter_results,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for key in ("base", "adapter"):
        if key in report:
            print(key, json.dumps(report[key]["summary"]["overall"], ensure_ascii=False))
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
