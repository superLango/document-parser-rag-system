"""Coverage pilot: outline, clause records, table links and audit (M1.7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import CoveragePlan, ItemInventory  # noqa: E402
from metal_doc_agent.coverage import (  # noqa: E402
    build_coverage_audit,
    build_links,
    build_outline,
)
from metal_doc_agent.extraction.clauses import extract_clauses  # noqa: E402
from metal_doc_agent.items import discover_items  # noqa: E402
from run_loader import load_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt40303_2021")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    run = load_run(run_dir)
    doc_id = run.document.doc_id or run_dir.name
    inventory_path = run_dir / "item_inventory.json"
    if inventory_path.exists():
        inventory = ItemInventory.model_validate_json(
            inventory_path.read_text(encoding="utf-8")
        )
    else:
        inventory = discover_items(
            run.pages,
            run.tables,
            run.bindings,
            run.cross_tasks,
            doc_id=doc_id,
            document_profile=run.doc_type,
        )

    outline = build_outline(run.document, run.pages)
    clause_output = extract_clauses(run.pages, run.document)
    links = build_links(doc_id, run.pages, run.tables)
    audit = build_coverage_audit(
        doc_id,
        run.pages,
        run.tables,
        inventory,
        links,
        bindings=run.bindings,
        records=run.records,
    )
    item_plan = CoveragePlan(
        standard_no=run.document.standard_no,
        template="item_inventory",
        items=audit.items,
    )

    out_dir = Path(args.out) if args.out else run_dir
    (out_dir / "outline.json").write_text(
        json.dumps(outline.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    with (out_dir / "clauses.jsonl").open("w", encoding="utf-8") as handle:
        for clause in clause_output.clauses:
            handle.write(
                json.dumps(clause.model_dump(mode="json"), ensure_ascii=False) + "\n"
            )
    (out_dir / "links.json").write_text(
        json.dumps(links.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "item_coverage_plan.json").write_text(
        json.dumps(item_plan.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "coverage_audit.json").write_text(
        json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    orphans = {
        "doc_id": doc_id,
        "tables": links.orphans,
        "rows": [
            gap for gap in audit.gaps if gap.get("type") == "orphan_row"
        ],
        "table_orphan_rate": round(
            len(links.orphans) / len(links.links), 4
        ) if links.links else 0.0,
    }
    (out_dir / "orphans.json").write_text(
        json.dumps(orphans, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "coverage_audit_report.md").write_text(
        _render_report(audit, links), encoding="utf-8"
    )
    print(
        f"clauses={len(clause_output.clauses)} tables={len(links.links)} "
        f"linked={links.coverage.get('linked', 0)} "
        f"link_rate={links.coverage.get('link_rate', 0)} "
        f"measure={audit.stats.get('measure_column_coverage', 0)} "
        f"mentions={audit.stats.get('clause_mentions', 0)} "
        f"unmapped_mentions={audit.stats.get('unmapped_mentions', 0)} "
        f"status={audit.status}"
    )
    print(f"out={out_dir}")
    return 0


def _render_report(audit, links) -> str:
    stats = audit.stats
    lines = [
        f"# 覆盖审计（M1.7）：{audit.doc_id}",
        "",
        f"- 状态：{audit.status}",
        f"- 项目：{stats.get('items', 0)}（confirmed {stats.get('confirmed', 0)} / "
        f"probable {stats.get('probable', 0)} / ambiguous {stats.get('ambiguous', 0)}）",
        f"- 未知候选：{stats.get('unknown_candidates', 0)}",
        f"- 测量列覆盖：{stats.get('measure_columns_mapped', 0)}/"
        f"{stats.get('measure_columns_total', 0)}"
        f"（{stats.get('measure_column_coverage', 0):.3f}）",
        f"- 表-条款链接：{stats.get('tables_linked', 0)}/{stats.get('tables', 0)}"
        f"（{stats.get('link_rate', 0):.3f}；显式 {stats.get('tables_explicit', 0)}）",
        f"- 条款项目提及：{stats.get('clause_mentions_mapped', 0)}/"
        f"{stats.get('clause_mentions', 0)}",
        f"- 孤儿表：{stats.get('orphan_tables', 0)}；孤儿行：{stats.get('orphan_rows', 0)}",
        f"- 未覆盖属性表：{stats.get('uncovered_tables', 0)}",
        "",
        "## 覆盖项",
        "",
        "| field | required | status | reason |",
        "|---|---|---|---|",
    ]
    for item in audit.items:
        lines.append(
            f"| {item.field} | {'是' if item.required else '否'} | "
            f"{item.status} | {item.reason or ''} |"
        )
    lines.extend(
        [
            "",
            "## 缺口",
            "",
            "| 类型 | 表/条款 | 位置 | 原因 |",
            "|---|---|---|---|",
        ]
    )
    for gap in audit.gaps[:100]:
        location = gap.get("table_id") or gap.get("clause_id") or ""
        position = gap.get("page_no") or ""
        if gap.get("column") is not None:
            position = f"{position} c{gap['column']}"
        if gap.get("row") is not None:
            position = f"{position} r{gap['row']}"
        lines.append(
            f"| {gap['type']} | {location} | {position} | {gap.get('reason', '')} |"
        )
    lines.extend(
        [
            "",
            "## 表-条款链接",
            "",
            "| 表 | 页 | 条款 | 依据 | 置信度 |",
            "|---|---|---|---|---|",
        ]
    )
    for link in links.links:
        lines.append(
            f"| {link.table_id} | {link.page_no or ''} | "
            f"{link.clause_id or '-'} | {link.basis} | {link.confidence:.2f} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
