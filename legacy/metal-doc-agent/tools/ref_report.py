"""Generate a reference-graph diagnostic report for M1.5.3.

This is not an accuracy evaluation: the reference gold set still needs human
annotation. The report measures parse coverage, dated-reference ratio, version
resolution, relevance mix and the 1-hop expansion budget across the 20-doc run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="runs/m1_qwen_ws2")
    parser.add_argument("--out", default="eval/ref_eval.md")
    args = parser.parse_args(argv)
    runs_dir = ROOT / args.runs
    out_path = ROOT / args.out

    rows = []
    totals = {
        "docs": 0,
        "refs": 0,
        "normative": 0,
        "clause": 0,
        "dated": 0,
        "resolved": 0,
        "gaps": 0,
        "selected": 0,
        "exceeded": 0,
    }
    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        path = run_dir / "references.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        refs = data.get("references", [])
        normative = sum(1 for item in refs if item.get("relation") == "normative")
        clause = sum(1 for item in refs if item.get("relation") == "clause")
        dated = sum(1 for item in refs if item.get("dated"))
        resolved = sum(1 for item in refs if item.get("resolved"))
        gaps = len(data.get("gaps", []))
        budget = data.get("budget", {})
        selected = budget.get("selected_documents", 0)
        exceeded = bool(budget.get("exceeded"))
        rows.append(
            (
                run_dir.name,
                len(refs),
                normative,
                clause,
                f"{dated}/{len(refs)}" if refs else "-",
                resolved,
                gaps,
                selected,
                "yes" if exceeded else "no",
            )
        )
        totals["docs"] += 1
        totals["refs"] += len(refs)
        totals["normative"] += normative
        totals["clause"] += clause
        totals["dated"] += dated
        totals["resolved"] += resolved
        totals["gaps"] += gaps
        totals["selected"] += selected
        totals["exceeded"] += 1 if exceeded else 0

    lines = [
        "# M1.5.3 引用解析诊断",
        "",
        "> 状态：**诊断报告，不是验收级评测**。`ref_gold.json` 仍需人工标注；",
        "> 在 gold 完成前不计算解析率/关键引用覆盖率，也不宣称 M1.5.3 达标。",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 文档数 | {totals['docs']} |",
        f"| 引用边 | {totals['refs']} |",
        f"| normative | {totals['normative']} |",
        f"| clause | {totals['clause']} |",
        f"| 注日期边 | {totals['dated']}/{totals['refs']} |",
        f"| 已解析 | {totals['resolved']} |",
        f"| 未解析缺口 | {totals['gaps']} |",
        f"| 已选 1 跳展开 | {totals['selected']} |",
        f"| 超预算文档 | {totals['exceeded']} |",
        "",
        "## 分文档",
        "",
        "| 文档 | 边 | normative | clause | 注日期 | 已解析 | gaps | 已选展开 | 超预算 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    lines.extend(
        [
            "",
            "## 结论与下一步",
            "",
            "- 引用解析器、版本库、相关性分类与 ≤8 份预算均已接入 pipeline；",
            "- 本地库只覆盖 20 份语料及少量工作区 PDF，真实引用几乎全部是外部标准，",
            "  因此当前已解析为 0，全部进入 gaps；",
            "- 下一步需（1）领域专家扩充本地标准库；（2）人工标注 `ref_gold.json`，",
            "  再计算解析率、关键引用覆盖率和注日期版本正确率。",
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path} ({totals['docs']} docs, {totals['refs']} refs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
