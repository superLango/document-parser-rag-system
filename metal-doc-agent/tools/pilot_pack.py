"""Pilot acceptance pack (M5.2-06).

Aggregates the closure evidence (SLO/load test, cost, quality, backup drill,
security scan, review capability) into one reviewable packet. It never claims
G5 passed: blockers stay explicit until a pilot department signs off.

Usage:
    python -m tools.pilot_pack --out eval/pilot-pack.json --md eval/pilot-pack.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", default=str(ROOT / "eval"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "pilot-pack.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "pilot-pack.md"))
    args = parser.parse_args(argv)

    eval_dir = Path(args.eval)
    m5 = _read(eval_dir / "m5.json")
    cost = _read(eval_dir / "m5-cost.json")
    load = _read(eval_dir / "loadtest.json")
    drill = _read(eval_dir / "backup-drill.json")
    scan = _read(eval_dir / "security-scan.json")
    sla = _read(eval_dir / "sla.json")
    m4 = _read(eval_dir / "m4.json")

    families = (m5.get("g5") or {}).get("families_operational", 0)
    quality = m5.get("quality") or {}
    g5_items = [
        {"item": "5 个标准族", "status": "pass" if families >= 5 else "gap", "evidence": f"{families}/5"},
        {
            "item": "证据率 ≥95%",
            "status": "pass" if (quality.get("evidence_rate") or 0) >= 0.95 else "gap",
            "evidence": quality.get("evidence_rate"),
        },
        {
            "item": "silent error = 0",
            "status": "pass" if quality.get("silent_errors", 1) == 0 else "gap",
            "evidence": quality.get("silent_errors"),
        },
        {
            "item": "p95 ≤5 分钟（离线）",
            "status": "pass" if (m5.get("g5") or {}).get("latency_p95_ok") else "gap",
            "evidence": (m5.get("latency") or {}).get("p95_ms"),
        },
        {
            "item": "并发压测失败率 <2%",
            "status": "pass"
            if (load.get("totals") or {}).get("failure_rate", 1) < 0.02
            else "gap",
            "evidence": (load.get("totals") or {}).get("failure_rate"),
        },
        {
            "item": "备份恢复演练",
            "status": "partial" if drill.get("passed") else "gap",
            "evidence": drill.get("mode") if drill.get("passed") else "not run",
        },
        {
            "item": "密钥扫描",
            "status": "pass" if scan.get("passed") else "gap",
            "evidence": len(scan.get("findings") or []),
        },
        {"item": "灰度/回滚清单", "status": "pass", "evidence": "infra/k8s/overlays/canary"},
        {"item": "成本/页", "status": "partial", "evidence": (cost.get("totals") or {}).get("cost_per_page")},
        {
            "item": "生产 SLA 99.5%",
            "status": "partial" if sla else "gap",
            "evidence": sla.get("status") or "无生产流量",
        },
        {"item": "外部安全评审", "status": "gap", "evidence": "security-review-package.md 已备"},
        {"item": "试点部门验收", "status": "gap", "evidence": "待签字"},
        {"item": "值班表", "status": "partial", "evidence": "runbook 已写，名单未定"},
    ]
    blockers = [item["item"] for item in g5_items if item["status"] in {"gap", "partial"}]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "g5_passed": False,
        "checklist": g5_items,
        "blockers": blockers,
        "evidence": {
            "m5": _summary(m5),
            "cost": cost.get("totals"),
            "loadtest": load.get("totals"),
            "backup_drill": {
                "passed": drill.get("passed"),
                "mode": drill.get("mode"),
                "checks": drill.get("checks"),
            },
            "security_scan": {"passed": scan.get("passed"), "findings": scan.get("findings")},
            "sla": {
                "status": sla.get("status"),
                "samples": (sla.get("window") or {}).get("sampled_jobs"),
                "p95_ms": sla.get("p95_ms"),
            },
            "quality": {
                "evidence_rate": quality.get("evidence_rate"),
                "silent_errors": quality.get("silent_errors"),
                "risk_fields": (m4.get("risk_fields") or {}),
            },
        },
        "signoff": [
            {"role": "业务负责人", "name": "", "date": "", "decision": "pending"},
            {"role": "技术负责人", "name": "", "date": "", "decision": "pending"},
            {"role": "安全负责人", "name": "", "date": "", "decision": "pending"},
            {"role": "运维负责人", "name": "", "date": "", "decision": "pending"},
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"g5_passed": False, "blockers": blockers}, ensure_ascii=False))
    print(f"out={out}")
    return 0


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _summary(m5: dict) -> dict:
    return {
        "families": (m5.get("g5") or {}).get("families_operational"),
        "latency": m5.get("latency"),
        "quality": m5.get("quality"),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# 试点验收包（M5）",
        "",
        f"- 结论：**{'通过' if report['g5_passed'] else '未通过'}**",
        f"- 阻塞项：{', '.join(report['blockers']) or '无'}",
        "",
        "## G5 检查",
        "",
        "| 项 | 状态 | 证据 |",
        "|---|---|---|",
    ]
    for item in report["checklist"]:
        lines.append(f"| {item['item']} | {item['status']} | {item['evidence']} |")
    lines.extend(
        [
            "",
            "## 证据",
            "",
            f"- M5：`{report['evidence']['m5']}`",
            f"- 成本：`{report['evidence']['cost']}`",
            f"- 压测：`{report['evidence']['loadtest']}`",
            f"- 备份演练：`{report['evidence']['backup_drill']}`",
            f"- 安全扫描：`{report['evidence']['security_scan']}`",
            f"- SLA：`{report['evidence']['sla']}`",
            "",
            "## 签字",
            "",
            "| 角色 | 姓名 | 日期 | 结论 |",
            "|---|---|---|---|",
        ]
    )
    for row in report["signoff"]:
        lines.append(f"| {row['role']} |  |  | 待签 |")
    lines.extend(
        [
            "",
            "> 未取得签字与生产 SLA 前，不视为 G5 通过，不对外承诺 SLA。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
