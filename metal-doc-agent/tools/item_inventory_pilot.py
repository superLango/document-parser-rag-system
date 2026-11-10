"""ItemInventory pilot (M1.7) on one run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.items import discover_items  # noqa: E402
from run_loader import load_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt40303_2021")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    if not (run_dir / "tablegrid").exists():
        print(f"no tablegrid under {run_dir}")
        return 1
    run = load_run(run_dir)
    inventory = discover_items(
        run.pages,
        run.tables,
        run.bindings,
        run.cross_tasks,
        doc_id=run.document.doc_id or run_dir.name,
        document_profile=run.doc_type,
    )
    out_dir = Path(args.out) if args.out else run_dir
    (out_dir / "item_inventory.json").write_text(
        json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "item_inventory_report.md").write_text(
        _render_report(inventory), encoding="utf-8"
    )
    print(
        f"items={len(inventory.items)} confirmed={inventory.coverage.get('confirmed', 0)} "
        f"probable={inventory.coverage.get('probable', 0)} "
        f"unknown={len(inventory.unknown_candidates)} "
        f"coverage={inventory.coverage.get('measure_column_coverage', 0)}"
    )
    print(f"out={out_dir}")
    return 0


def _render_report(inventory) -> str:
    coverage = inventory.coverage
    lines = [
        f"# 项目清单（ItemInventory）：{inventory.doc_id}",
        "",
        f"- 项目数：{coverage.get('items', 0)}",
        f"- 已确认：{coverage.get('confirmed', 0)}",
        f"- 待确认：{coverage.get('probable', 0)}",
        f"- 歧义：{coverage.get('ambiguous', 0)}",
        f"- 未知候选：{coverage.get('unknown_candidates', 0)}",
        f"- 测量列覆盖：{coverage.get('measure_columns_mapped', 0)}/"
        f"{coverage.get('measure_columns_total', 0)}"
        f"（{coverage.get('measure_column_coverage', 0):.3f}）",
        f"- 未映射列：{coverage.get('unmapped_columns', 0)}",
        "",
        "| 项目 | 规范名 | family | facets | 属性 | 方法 | 来源 | 状态 | 页 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in inventory.items:
        lines.append(
            f"| {item.item_raw} | {item.item_canonical or ''} | {item.item_family} | "
            f"{json.dumps(item.facets, ensure_ascii=False)} | "
            f"{'、'.join(item.properties)} | {item.method_standard or ''} | "
            f"{item.source} | {item.status} | {item.page_no or ''} |"
        )
    if inventory.unknown_candidates:
        lines.extend(
            [
                "",
                "## 未知候选",
                "",
                "| raw | 来源 | 页/表 | 原因 |",
                "|---|---|---|---|",
            ]
        )
        for item in inventory.unknown_candidates:
            lines.append(
                f"| {item.get('raw', '')} | {item.get('source', '')} | "
                f"{item.get('page_no', '')}/{item.get('table_id', '')} | "
                f"{item.get('reason', '')} |"
            )
    if inventory.not_applicable:
        lines.extend(["", "## 不适用", ""])
        for item in inventory.not_applicable:
            lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
