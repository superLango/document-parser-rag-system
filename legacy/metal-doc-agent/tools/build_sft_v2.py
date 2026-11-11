"""Build SFT v2: constrained header mapping + engine-canonical gold outputs.

Why v2: the first sft_m2 pipeline run lost ~0.03 field F1 even with the base
model, because the SFT header prompt lacked ``allowed_properties`` /
``profile`` and the gold property names included keys the engine cannot map.
v2 fixes both: every header sample carries the same constraint fields the
engine sends, and gold properties are canonicalised to the engine vocabulary
(unknown names become ``ignore``).

Output:
* ``train.jsonl``: train + dev samples
* ``eval.jsonl``: heldout samples
* ``report.json``: task counts, canonicalisation drops, source metadata
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from metal_doc_agent.extraction.qwen import ALLOWED_PROPERTIES
from metal_doc_agent.extraction.sft_prompts import INSTRUCTIONS, SYSTEM
from metal_doc_agent.tablegrid.normalize import (
    ELEMENTS,
    canonical_element,
    canonical_property,
)

ROOT = Path(__file__).resolve().parents[1]
HEADER_TASK = "header_mapping_constrained"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT / "data" / "m2" / "train-v1"))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--out", default=str(ROOT / "data" / "m2" / "sft-v2"))
    args = parser.parse_args(argv)

    source = Path(args.dataset)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = Path(args.runs)

    train_stats: Counter[str] = Counter()
    eval_stats: Counter[str] = Counter()
    train: list[dict[str, Any]] = []
    for path in ("train.jsonl", "dev.jsonl"):
        train.extend(_convert(_load(source / path), runs_dir, train_stats))
    evaluation = _convert(_load(source / "heldout.jsonl"), runs_dir, eval_stats)
    _write(out_dir / "train.jsonl", train)
    _write(out_dir / "eval.jsonl", evaluation)

    report = {
        "source": source.as_posix(),
        "runs": runs_dir.as_posix(),
        "variant": "sft-v2",
        "notes": (
            "header_mapping_constrained carries caption/profile/orientation/n_cols "
            "and allowed_properties/allowed_elements; gold properties are mapped to "
            "the engine vocabulary, unknown names become ignore"
        ),
        "train": _counts(train, train_stats),
        "eval": _counts(evaluation, eval_stats),
        "system_prompt": SYSTEM,
        "header_instruction": INSTRUCTIONS[HEADER_TASK],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"train": len(train), "eval": len(evaluation)}, ensure_ascii=False))
    print(f"out={out_dir}")
    return 0


def _convert(
    rows: list[dict[str, Any]], runs_dir: Path, stats: Counter[str]
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for row in rows:
        task = row["task"]
        if task == "header_mapping":
            payload, output = _constrained_header(row, runs_dir, stats)
            instruction = INSTRUCTIONS[HEADER_TASK]
            out_task = HEADER_TASK
        elif task in {"row_record", "row_record_perturb"}:
            payload, output = _canonical_row(row, stats)
            instruction = INSTRUCTIONS["row_record"]
            out_task = task
        else:
            instruction = INSTRUCTIONS.get(task)
            if instruction is None:
                continue
            payload, output, out_task = row["input"], row["output"], task
        converted.append(
            {
                "id": f"{row['doc_id']}:{out_task}:{len(converted)}",
                "task": out_task,
                "doc_id": row["doc_id"],
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": instruction
                        + "\n输入："
                        + json.dumps(payload, ensure_ascii=False),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(output, ensure_ascii=False),
                    },
                ],
            }
        )
    return converted


def _constrained_header(
    row: dict[str, Any], runs_dir: Path, stats: Counter[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = _tablegrid(runs_dir, row["doc_id"], row["table_id"])
    header_paths = row["input"].get("header_paths") or []
    payload = {
        "caption": (source or {}).get("caption"),
        "profile": (source or {}).get("profile") or row.get("profile"),
        "orientation": (source or {}).get("orientation") or "grade_rows",
        "n_cols": (source or {}).get("n_cols") or len(header_paths),
        "header_paths": header_paths,
        "sample_rows": row["input"].get("sample_rows") or [],
        "allowed_properties": list(ALLOWED_PROPERTIES),
        "allowed_elements": sorted(ELEMENTS),
    }
    columns = []
    for column in row["output"].get("columns") or []:
        role = str(column.get("role") or "ignore").lower()
        if role == "property":
            name = canonical_element(column.get("property")) if payload["profile"] == (
                "chemical_composition"
            ) else canonical_property(column.get("property"))
            if not name:
                stats["header_property_dropped"] += 1
                columns.append({"index": column["index"], "role": "ignore"})
                continue
            columns.append(
                {
                    "index": column["index"],
                    "role": "property",
                    "property": name,
                    "unit": column.get("unit"),
                }
            )
        elif role in {"grade", "condition"}:
            columns.append({"index": column["index"], "role": role})
        else:
            columns.append({"index": column["index"], "role": "ignore"})
    stats["header_samples"] += 1
    return payload, {"columns": columns}


def _canonical_row(
    row: dict[str, Any], stats: Counter[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = row.get("profile")
    output = dict(row["output"])
    properties = {}
    for name, value in (output.get("properties") or {}).items():
        canonical = (
            canonical_element(name)
            if profile == "chemical_composition"
            else canonical_property(name)
        )
        if not canonical:
            stats["row_property_dropped"] += 1
            continue
        properties[canonical] = value
    output["properties"] = properties
    stats["row_samples"] += 1
    return row["input"], output


def _tablegrid(runs_dir: Path, doc_id: str, table_id: str) -> dict[str, Any] | None:
    path = runs_dir / doc_id / "tablegrid" / f"{table_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _counts(rows: list[dict[str, Any]], stats: Counter[str]) -> dict[str, Any]:
    counts = Counter(row["task"] for row in rows)
    lengths = [sum(len(message["content"]) for message in row["messages"]) for row in rows]
    return {
        "total": len(rows),
        "by_task": dict(counts),
        "chars_min": min(lengths) if lengths else 0,
        "chars_max": max(lengths) if lengths else 0,
        "chars_avg": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "header_property_dropped": stats["header_property_dropped"],
        "row_property_dropped": stats["row_property_dropped"],
    }


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
