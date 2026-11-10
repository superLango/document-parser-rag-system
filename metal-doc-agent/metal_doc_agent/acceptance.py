"""M1-S8 full-corpus acceptance report.

This is a gate, not a dashboard: it checks the 20-document run for schema,
artifacts, evidence, coverage, latency, error attribution and G1 thresholds,
then prints a go/no-go decision.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import verify_artifacts
from .contracts import DocumentResult
from .eval.metrics import evaluate_goldset
from .goldset import load_manifest


@dataclass
class Check:
    check_id: str
    name: str
    actual: Any
    target: Any
    passed: bool
    blocking: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "name": self.name,
            "actual": self.actual,
            "target": self.target,
            "passed": self.passed,
            "blocking": self.blocking,
            "detail": self.detail,
        }


@dataclass
class AcceptanceReport:
    generated_at: str
    runs_dir: str
    goldset_version: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def go_no_go(self) -> str:
        return "GO" if all(c.passed for c in self.checks if c.blocking) else "NO-GO"

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "runs_dir": self.runs_dir,
            "goldset_version": self.goldset_version,
            "decision": self.go_no_go,
            "documents": self.documents,
            "checks": [check.to_dict() for check in self.checks],
            "metrics": self.metrics,
        }


def run_acceptance(goldset_dir: str | Path, runs_dir: str | Path) -> AcceptanceReport:
    gold_dir = Path(goldset_dir)
    run_root = Path(runs_dir)
    manifest = load_manifest(gold_dir / "manifest.json")
    payload = evaluate_goldset(gold_dir, run_root)
    summary = payload["summary"]

    documents: list[dict[str, Any]] = []
    for entry in manifest.documents:
        run_dir = run_root / entry.doc_id
        row = _document_row(entry.doc_id, run_dir)
        documents.append(row)

    schema_rate = _rate(sum(row["schema_ok"] for row in documents), len(documents))
    artifact_rate = _rate(sum(row["artifacts_ok"] for row in documents), len(documents))
    simple_field_f1 = _profile_field_f1(
        summary.get("by_profile", {}), ("chemical_composition", "mechanical_properties")
    )
    scanned_field_f1 = _group_field_f1(payload["documents"], "scanned")
    elapsed = _p95([row["elapsed_ms"] for row in documents if row["pages"] >= 30])
    if not elapsed:
        elapsed = _p95([row["elapsed_ms"] for row in documents])
    evidence = summary.get("evidence_rate", 0.0)
    hallucination = round(1.0 - evidence, 4) if evidence else 1.0
    taxonomy_ok = {"ocr", "header", "normalization", "semantic", "reference", "coverage"} <= set(
        summary.get("error_categories", {})
    ) and all(
        error.get("category")
        for doc in payload["documents"]
        for error in doc.get("errors", [])
    )
    hard_tables = payload.get("hard_tables", [])
    annotation_status = _annotation_statuses(manifest, gold_dir)
    verified = annotation_status.get("verified", 0) == len(manifest.documents)

    checks = [
        Check("documents", "20 份文档全部产出 result", len(documents), 20, len(documents) == 20),
        Check("schema", "result Schema 通过率", schema_rate, 1.0, schema_rate == 1.0),
        Check("artifacts", "artifact 清单校验通过率", artifact_rate, 1.0, artifact_rate == 1.0),
        Check(
            "evidence",
            "证据覆盖率",
            evidence,
            0.95,
            evidence >= 0.95,
            detail="有 evidence_id 且存在于 evidence.jsonl",
        ),
        Check(
            "simple_fields",
            "简单表核心字段 Field F1",
            simple_field_f1,
            0.85,
            simple_field_f1 >= 0.85,
            detail="chemical_composition + mechanical_properties",
        ),
        Check(
            "scanned_fields",
            "扫描件核心字段 Field F1",
            scanned_field_f1,
            0.75,
            scanned_field_f1 >= 0.75,
        ),
        Check(
            "latency",
            "30 页文档 p95 耗时（ms）",
            elapsed,
            300000,
            elapsed <= 300000,
        ),
        Check(
            "hallucination",
            "数值幻觉率",
            hallucination,
            0.01,
            hallucination < 0.01,
            detail="1 - evidence_rate",
        ),
        Check(
            "hard_tables",
            "困难表单独报告",
            len(hard_tables),
            ">0",
            bool(hard_tables),
        ),
        Check(
            "error_taxonomy",
            "错误分类完整",
            summary.get("error_categories", {}),
            "six categories",
            taxonomy_ok,
        ),
        Check(
            "annotation_review",
            "20 份标注 verified",
            annotation_status,
            "20 verified",
            verified,
            detail="A/B 复核与仲裁完成后才可 G1 通过",
        ),
    ]

    return AcceptanceReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        runs_dir=str(run_root.resolve()),
        goldset_version=manifest.goldset_version,
        documents=documents,
        checks=checks,
        metrics=summary,
    )


def _document_row(doc_id: str, run_dir: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "doc_id": doc_id,
        "schema_ok": False,
        "artifacts_ok": False,
        "pages": 0,
        "tables": 0,
        "records": 0,
        "evidence": 0,
        "status": "missing",
        "elapsed_ms": 0.0,
    }
    result_path = run_dir / "result.json"
    if not result_path.exists():
        return row
    try:
        result = DocumentResult.model_validate(
            json.loads(result_path.read_text(encoding="utf-8"))
        )
        row["schema_ok"] = True
        row["pages"] = result.document.page_count
        row["tables"] = len(result.tables)
        row["records"] = len(result.records)
        row["status"] = result.quality.status if result.quality else "unknown"
    except Exception as exc:  # noqa: BLE001 - acceptance reports the failure
        row["status"] = f"schema_error: {str(exc)[:120]}"
        return row

    evidence_path = run_dir / "evidence.jsonl"
    if evidence_path.exists():
        row["evidence"] = sum(
            1 for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    row["artifacts_ok"] = verify_artifacts(run_dir).ok
    trace_path = run_dir / "trace.json"
    if trace_path.exists():
        try:
            row["elapsed_ms"] = float(
                json.loads(trace_path.read_text(encoding="utf-8")).get("elapsed_ms", 0.0)
            )
        except (ValueError, json.JSONDecodeError):
            row["elapsed_ms"] = 0.0
    return row


def _annotation_statuses(manifest: Any, gold_dir: Path) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for entry in manifest.documents:
        if not entry.annotation_file:
            statuses["missing"] = statuses.get("missing", 0) + 1
            continue
        try:
            data = json.loads((gold_dir / entry.annotation_file).read_text(encoding="utf-8"))
            status = data.get("annotation", {}).get("status", "draft")
        except (OSError, json.JSONDecodeError):
            status = "missing"
        statuses[status] = statuses.get(status, 0) + 1
    return statuses


def _profile_field_f1(by_profile: dict[str, Any], profiles: tuple[str, ...]) -> float:
    totals = {"field_tp": 0, "field_fp": 0, "field_fn": 0}
    for profile in profiles:
        counts = by_profile.get(profile, {}).get("counts", {})
        for name in totals:
            totals[name] += counts.get(name, 0)
    tp, fp, fn = totals["field_tp"], totals["field_fp"], totals["field_fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _group_field_f1(documents: list[dict[str, Any]], source_type: str) -> float:
    totals = {"field_tp": 0, "field_fp": 0, "field_fn": 0}
    for doc in documents:
        if doc.get("source_type") != source_type:
            continue
        for name in totals:
            totals[name] += doc.get("counts", {}).get(name, 0)
    tp, fp, fn = totals["field_tp"], totals["field_fp"], totals["field_fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 2)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def render_acceptance(report: AcceptanceReport) -> str:
    lines = [
        "# M1-S8 全量验收报告",
        "",
        f"- 生成时间：{report.generated_at}",
        f"- 运行目录：`{report.runs_dir}`",
        f"- goldset：{report.goldset_version}",
        f"- 结论：**{report.go_no_go}**",
        "",
        "## 验收检查",
        "",
        "| 检查 | 实际 | 目标 | 结果 | 阻断 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for check in report.checks:
        lines.append(
            f"| {check.name} | {check.actual} | {check.target} | "
            f"{'PASS' if check.passed else 'FAIL'} | {'是' if check.blocking else '否'} | {check.detail} |"
        )
    lines.extend(
        [
            "",
            "## 关键指标",
            "",
            "| 指标 | 值 |",
            "|---|---|",
        ]
    )
    for name in (
        "record_f1",
        "field_f1",
        "value_accuracy",
        "evidence_rate",
        "coverage_rate",
    ):
        lines.append(f"| {name} | {report.metrics.get(name, 0.0)} |")
    lines.extend(
        [
            "",
            "## 分文档",
            "",
            "| 文档 | Schema | Artifacts | 页 | 表 | 记录 | 证据 | 审核 | 耗时 ms |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report.documents:
        lines.append(
            f"| {row['doc_id']} | {'OK' if row['schema_ok'] else 'FAIL'} | "
            f"{'OK' if row['artifacts_ok'] else 'FAIL'} | {row['pages']} | {row['tables']} | "
            f"{row['records']} | {row['evidence']} | {row['status']} | {row['elapsed_ms']} |"
        )
    lines.extend(["", "## 阻断项", ""])
    if report.blockers:
        for check in report.blockers:
            lines.append(
                f"- {check.name}：实际 {check.actual}，目标 {check.target}"
                + (f"（{check.detail}）" if check.detail else "")
            )
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- GO：全部阻断检查通过，可进入 G1 评审。",
            "- NO-GO：先处理上方阻断项；当前 mock 基线不是准确率目标，真实 Qwen 评测需在模型设备重跑。",
        ]
    )
    return "\n".join(lines)


def write_acceptance(report: AcceptanceReport, out_dir: str | Path) -> dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "acceptance.json"
    md_path = target / "acceptance.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_acceptance(report) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
