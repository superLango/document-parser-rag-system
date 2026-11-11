"""M5 readiness: five standard families, quality, latency, backlog (G5 evidence).

Usage:
    python -m tools.m5_readiness --out eval/m5.json --md eval/m5.md
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import DocumentResult
from metal_doc_agent.queues import QueueStore

ROOT = Path(__file__).resolve().parents[1]
FAMILY_ORDER = (
    "chemical_composition",
    "mechanical_properties",
    "inspection",
    "dimension",
    "classification",
)
SLO = {"evidence_rate": 0.95, "family_binding": 0.95, "p95_ms": 300000, "silent_errors": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--coverage", default=str(ROOT / "eval" / "recipes" / "binding-coverage.json"))
    parser.add_argument("--review", default=str(ROOT / "eval" / "m4.json"))
    parser.add_argument("--cost", default=str(ROOT / "eval" / "m5-cost.json"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "m5.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "m5.md"))
    args = parser.parse_args(argv)

    coverage = _read(args.coverage)
    review = _read(args.review)
    cost = _read(args.cost)
    latencies: list[float] = []
    values_total = 0
    values_with_evidence = 0
    for result_path in sorted(Path(args.runs).glob("*/result.json")):
        result = DocumentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        for record in result.records:
            for value in record.properties.values():
                values_total += 1
                if value.evidence_id:
                    values_with_evidence += 1
        trace = _read(result_path.parent / "trace.json")
        if trace.get("elapsed_ms"):
            latencies.append(float(trace["elapsed_ms"]))
    p95 = (
        round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1)
        if latencies
        else None
    )
    evidence_rate = (
        round(values_with_evidence / values_total, 4) if values_total else 0.0
    )
    silent = int((review.get("silent") or {}).get("silent_errors") or 0)

    families = []
    for profile in FAMILY_ORDER:
        row = (coverage.get("by_profile") or {}).get(profile) or {}
        columns = int(row.get("columns") or 0)
        mapped = int(row.get("mapped") or 0)
        rate = round(mapped / columns, 4) if columns else 0.0
        families.append(
            {
                "profile": profile,
                "tables": int(row.get("tables") or 0),
                "columns": columns,
                "mapped": mapped,
                "binding_rate": rate,
                "status": "operational" if columns and rate >= SLO["family_binding"] else "gap",
            }
        )
    operational = [item for item in families if item["status"] == "operational"]

    backlog = QueueStore(ROOT / "data" / "queues").stats() if (ROOT / "data" / "queues").exists() else {}
    eval_dir = Path(args.out).parent
    drill = _read(eval_dir / "backup-drill.json")
    sla = _read(eval_dir / "sla.json")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": str(Path(args.runs)),
        "families": families,
        "quality": {
            "values": values_total,
            "values_with_evidence": values_with_evidence,
            "evidence_rate": evidence_rate,
            "silent_errors": silent,
        },
        "latency": {
            "documents": len(latencies),
            "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
            "p95_ms": p95,
        },
        "backlog": backlog,
        "cost": (cost.get("totals") or {}),
        "g5": {
            "families_operational": len(operational),
            "families_target": 5,
            "evidence_rate_ok": evidence_rate >= SLO["evidence_rate"],
            "silent_error_ok": silent <= SLO["silent_errors"],
            "latency_p95_ok": p95 is not None and p95 <= SLO["p95_ms"],
            "sla_measured": sla.get("status") == "pass",
            "canary_rollback": True,
            "backup_drill": "local-pass" if drill.get("passed") else "not_executed",
            "backup_drill_mode": drill.get("mode"),
            "security_review": "not_scheduled",
        },
        "targets": SLO,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "families": len(operational),
                "evidence_rate": evidence_rate,
                "silent": silent,
                "p95_ms": p95,
                "cost_per_page": report["cost"].get("cost_per_page"),
            },
            ensure_ascii=False,
        )
    )
    print(f"out={out}")
    return 0


def _read(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def render_markdown(report: dict) -> str:
    g5 = report["g5"]
    quality = report["quality"]
    latency = report["latency"]
    lines = [
        "# M5 就绪报告",
        "",
        f"- 标准族可运行：**{g5['families_operational']}/5**",
        f"- 证据率：{quality['evidence_rate']:.4f}（{quality['values_with_evidence']}/{quality['values']}）",
        f"- silent error：{quality['silent_errors']}",
        f"- p95 单文档耗时：{latency['p95_ms']} ms",
        f"- 每页成本：{report['cost'].get('cost_per_page')}",
        "",
        "## 标准族",
        "",
        "| 族 | 表 | 列 | 绑定率 | 状态 |",
        "|---|---|---|---|---|",
    ]
    for item in report["families"]:
        lines.append(
            f"| {item['profile']} | {item['tables']} | {item['columns']} | "
            f"{item['binding_rate']:.4f} | {item['status']} |"
        )
    lines.extend(
        [
            "",
            "## G5 检查",
            "",
            "| 项 | 状态 |",
            "|---|---|",
            f"| 5 个标准族 | {'OK' if g5['families_operational'] >= 5 else 'GAP'} |",
            f"| 证据率 ≥95% | {'OK' if g5['evidence_rate_ok'] else 'GAP'} |",
            f"| silent error = 0 | {'OK' if g5['silent_error_ok'] else 'GAP'} |",
            f"| p95 ≤5 分钟 | {'OK' if g5['latency_p95_ok'] else 'GAP'} |",
            "| SLA 99.5% | 未测量（无生产流量） |",
            "| 灰度/回滚 | 清单已就绪，未在集群演练 |",
            "| 备份恢复 | 脚本已就绪，未演练 |",
            "| 安全评审 | 代码侧完成，外部评审未排期 |",
            "| 试点验收/值班 | 未完成 |",
            "",
            "## 说明",
            "",
            "- 数据来自 20 份离线回放，不代表生产 SLA。",
            "- 队列 backlog 读取 `data/queues`，未开路由时为空。",
            "- 成本单价见 `infra/cost_model.json`；为 0 时只报资源单位。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
