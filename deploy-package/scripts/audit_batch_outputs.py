#!/usr/bin/env python3
"""批次产出健康检查：解释“为什么没有 JSON/记录”。

对每个文档目录检查 OCR markdown、结果 JSON 与记录数，并按文档内容判断
是否属于可抽取的材料/采购/技术协议类文档。输出 Markdown 分流表。

用法：
  python audit_batch_outputs.py --root /data/标准拆分提取-... --out /out/batch-audit.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MATERIAL_HINTS = (
    "化学成分",
    "力学性能",
    "室温拉伸",
    "抗拉强度",
    "屈服强度",
    "冲击",
    "硬度",
    "晶粒度",
    "非金属夹杂",
    "低倍",
    "超声",
    "尺寸",
    "外观",
    "表面质量",
)
NON_MATERIAL_HINTS = (
    "质量保证",
    "质保",
    "程序",
    "会议纪要",
    "审查意见",
    "不符合项",
    "防造假",
    "图纸",
    "取样图",
    "清单",
    "通知",
    "联络函",
)


def read_markdown(folder: Path) -> str:
    paths = list(folder.glob("*.md"))
    if not paths:
        return ""
    return paths[0].read_text(encoding="utf-8", errors="ignore")


def read_records(folder: Path) -> tuple[bool, int]:
    paths = list(folder.glob("*.json"))
    if not paths:
        return False, 0
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, 0
    records = payload.get("records") or []
    result = payload.get("result")
    if isinstance(result, dict) and not records:
        records = result.get("records") or []
    return True, len(records)


def classify(text: str) -> str:
    hits = sum(1 for hint in MATERIAL_HINTS if hint in text)
    non_material = sum(1 for hint in NON_MATERIAL_HINTS if hint in text)
    if hits >= 2 and hits > non_material:
        return "material"
    if non_material >= 2:
        return "non_material"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    root = Path(args.root)
    rows = []
    for folder in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: int(path.name) if path.name.isdigit() else 99999,
    ):
        markdown = read_markdown(folder)
        has_json, records = read_records(folder)
        if not markdown:
            state = "missing_ocr"
        elif not has_json:
            state = "missing_result"
        elif not records:
            state = "empty_result"
        else:
            state = "ok"
        kind = classify(markdown) if markdown else "unknown"
        rows.append(
            {
                "folder": folder.name,
                "state": state,
                "kind": kind,
                "md_chars": len(markdown),
                "records": records,
                "name": next(
                    (path.stem for path in folder.glob("*.md")),
                    next((path.name for path in folder.glob("*.pdf")), ""),
                ),
            }
        )

    states = Counter(row["state"] for row in rows)
    kinds = Counter((row["state"], row["kind"]) for row in rows)
    lines = [
        "# 批次产出健康检查",
        "",
        f"- 目录：`{root}`",
        f"- 文档数：{len(rows)}",
        f"- 状态：{dict(sorted(states.items()))}",
        "",
        "| 状态 | material | non_material | unknown |",
        "|---|---:|---:|---:|",
    ]
    for state in sorted(states):
        lines.append(
            f"| {state} | {kinds[(state, 'material')]} | "
            f"{kinds[(state, 'non_material')]} | {kinds[(state, 'unknown')]} |"
        )
    lines += ["", "## 明细", "", "| # | 文件 | 状态 | 类别 | MD 字符 | 记录 |", "|---:|---|---|---|---:|---:|"]
    for row in rows:
        lines.append(
            f"| {row['folder']} | {row['name'][:60]} | {row['state']} | "
            f"{row['kind']} | {row['md_chars']} | {row['records']} |"
        )
    output = "\n".join(lines) + "\n"
    print(output)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
