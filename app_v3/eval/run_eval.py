"""固定评测入口：沿用冻结 v5 matcher，对 26 份基准文档计算覆盖率/一致率/多余率。

用法：
  python -m app_v3.eval.run_eval \
    --gold-dir app_v3/benchmark/gold \
    --pred-root .tmp/batch20 \
    --pred-template "{doc}/extract/assembled/assembly-report.json"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .matcher import compare, load_gold, load_ours

DEFAULT_DOCS = [
    "asme-sb338-2025", "ams-4928x", "iso-5832-3-2021", "hb-20079-2012",
    "gjb-9581-2018", "gjb-2351a-2021", "gjb-2296a-2005", "gjb-1951a-2020",
    "gbt-14976-2025", "gbt-8547-2019", "gbt-5231-2022", "gbt-3623-2022",
    "gbt-3620-1-2016", "gbt-3077-2015", "gbt-2965-2023", "gbt-2054-2023",
    "astm-b348-25", "nbt-47019-8-2011", "xx454-2022", "yst-656-2015",
]


def evaluate(gold_dir: Path, pred_root: Path, template: str, docs: list[str]) -> dict:
    rows = []
    total_matched = total_exact = total_gold = total_ours = 0
    for doc in docs:
        gold_path = gold_dir / f"{doc}.json"
        pred_path = pred_root / template.format(doc=doc)
        if not gold_path.exists():
            rows.append({"doc": doc, "error": "missing_gold"})
            continue
        if not pred_path.exists():
            rows.append({"doc": doc, "error": "missing_prediction", "path": str(pred_path)})
            continue
        result = compare(load_gold(gold_path), load_ours(pred_path))
        gold_total = sum(result["by_category"].values())
        total_matched += result["matched"]
        total_exact += result["value_exact"]
        total_gold += gold_total
        total_ours += result["ours"]
        rows.append({
            "doc": doc,
            "gold": gold_total,
            "ours": result["ours"],
            "matched": result["matched"],
            "value_exact": result["value_exact"],
            "consistency": result["value_consistency"],
            "coverage": round(result["matched"] / gold_total, 4) if gold_total else 0.0,
            "missing": result["missing"],
            "extra": result["extra"],
            "missing_by_category": result["missing_by_category"],
            "extra_by_category": result["extra_by_category"],
        })
    summary = {
        "docs": len(rows),
        "gold": total_gold,
        "ours": total_ours,
        "matched": total_matched,
        "value_exact": total_exact,
        "consistency": round(total_exact / total_matched, 4) if total_matched else 0.0,
        "coverage": round(total_matched / total_gold, 4) if total_gold else 0.0,
        "missing": total_gold - total_matched,
        "extra": total_ours - total_matched if total_ours >= total_matched else 0,
        "rows": rows,
    }
    return summary


def render_table(summary: dict) -> str:
    lines = ["| 文档 | 金标 | 匹配 | 一致率 | 覆盖率 | 缺失 | 多余 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary["rows"]:
        if "error" in row:
            lines.append(f"| {row['doc']} | - | - | - | - | - | - |")
            continue
        lines.append(f"| {row['doc']} | {row['gold']} | {row['matched']} | {row['consistency']:.4f} | "
                     f"{row['coverage']:.4f} | {row['missing']} | {row['extra']} |")
    lines.append(f"| **合计** | **{summary['gold']}** | **{summary['matched']}** | "
                 f"**{summary['consistency']:.4f}** | **{summary['coverage']:.4f}** | "
                 f"**{summary['missing']}** | **{summary['extra']}** |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--pred-root", required=True)
    parser.add_argument("--pred-template", default="{doc}/extract/assembled/assembly-report.json")
    parser.add_argument("--docs", default="", help="逗号分隔；缺省 20 份批量文档")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    docs = [item.strip() for item in args.docs.split(",") if item.strip()] or DEFAULT_DOCS
    summary = evaluate(Path(args.gold_dir), Path(args.pred_root), args.pred_template, docs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[eval] docs={summary['docs']} matched={summary['matched']}/{summary['gold']} "
          f"consistency={summary['consistency']:.4f} coverage={summary['coverage']:.4f} "
          f"missing={summary['missing']} extra={summary['extra']} -> {output}", flush=True)
    print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
