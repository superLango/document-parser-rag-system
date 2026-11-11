"""Convert M2 task samples into chat-style SFT data for Qwen3.5-9B LoRA.

Output:
* ``train.jsonl``: train + dev samples (document-level split, heldout untouched)
* ``eval.jsonl``: heldout samples for validation
* ``report.json``: task counts and token-length hints

Each row: ``{"id": ..., "task": ..., "messages": [system, user, assistant]}``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from metal_doc_agent.extraction.sft_prompts import INSTRUCTIONS, SYSTEM

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT / "data" / "m2" / "train-v1"))
    parser.add_argument("--out", default=str(ROOT / "data" / "m2" / "sft-v1"))
    args = parser.parse_args(argv)

    source = Path(args.dataset)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    train = _convert(_load(source / "train.jsonl")) + _convert(_load(source / "dev.jsonl"))
    evaluation = _convert(_load(source / "heldout.jsonl"))
    _write(out_dir / "train.jsonl", train)
    _write(out_dir / "eval.jsonl", evaluation)
    report = {
        "source": _relative(source),
        "train": _counts(train),
        "eval": _counts(evaluation),
        "system_prompt": SYSTEM,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"train": report["train"]["total"], "eval": report["eval"]["total"]}))
    print(f"out={out_dir}")
    return 0


def _convert(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for index, row in enumerate(rows):
        instruction = INSTRUCTIONS.get(row["task"])
        if instruction is None:
            continue
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": instruction
                + "\n输入："
                + json.dumps(row["input"], ensure_ascii=False),
            },
            {
                "role": "assistant",
                "content": json.dumps(row["output"], ensure_ascii=False),
            },
        ]
        converted.append(
            {
                "id": f"{row['doc_id']}:{row['task']}:{index}",
                "task": row["task"],
                "doc_id": row["doc_id"],
                "messages": messages,
            }
        )
    return converted


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["task"] for row in rows)
    lengths = [sum(len(message["content"]) for message in row["messages"]) for row in rows]
    return {
        "total": len(rows),
        "by_task": dict(counts),
        "chars_min": min(lengths) if lengths else 0,
        "chars_max": max(lengths) if lengths else 0,
        "chars_avg": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
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


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
