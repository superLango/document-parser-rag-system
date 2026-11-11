"""Accuracy + latency report for engine runs.

Inputs are a goldset evaluation directory (``metal_doc_agent.cli eval``) and a
run root with ``timings.jsonl``. The report adds latency percentiles, evidence
quality, silent-error audit and a Qwen-vs-mock field comparison.

Usage:
    python -m tools.extraction_report --gold-runs runs/qwen_gold_v2 \
      --mock-runs runs/m2_baseline --eval eval/qwen-gold-v2 \
      --diverse-runs runs/qwen_diverse \
      --out eval/extraction-report.json --md eval/extraction-report.md
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from metal_doc_agent.contracts import DocumentResult, Evidence
from metal_doc_agent.review import audit_document

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-runs", required=True)
    parser.add_argument("--mock-runs", default="")
    parser.add_argument("--eval", default="")
    parser.add_argument("--diverse-runs", default="")
    parser.add_argument("--out", default=str(ROOT / "eval" / "extraction-report.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "extraction-report.md"))
    args = parser.parse_args(argv)

    gold_runs = Path(args.gold_runs)
    latency = _latency(gold_runs / "timings.jsonl")
    usage = _usage(gold_runs)
    latency.update(usage)
    quality = _quality(gold_runs)
    report = {
        "gold_runs": gold_runs.as_posix(),
        "accuracy": _accuracy(Path(args.eval)) if args.eval else {},
        "latency": latency,
        "quality": quality,
        "agreement": _agreement(gold_runs, Path(args.mock_runs)) if args.mock_runs else {},
        "diverse": _latency(Path(args.diverse_runs) / "timings.jsonl") if args.diverse_runs else {},
        "diverse_quality": _quality(Path(args.diverse_runs)) if args.diverse_runs else {},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "documents": latency.get("documents"),
                "p50_s": latency.get("p50_s"),
                "p95_s": latency.get("p95_s"),
                "field_f1": report["accuracy"].get("field_f1"),
                "agreement": report["agreement"].get("field_agreement"),
            },
            ensure_ascii=False,
        )
    )
    print(f"out={out}")
    return 0


def _accuracy(eval_dir: Path) -> dict:
    path = eval_dir / "eval.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = dict(payload.get("summary") or {})
    summary["documents"] = (summary.get("documents")) or len(payload.get("documents") or [])
    summary["per_document"] = [
        {
            "doc_id": item.get("doc_id"),
            "record_f1": item.get("record_f1"),
            "field_f1": item.get("field_f1"),
            "value_accuracy": item.get("value_accuracy"),
        }
        for item in payload.get("documents") or []
    ]
    return summary


def _latency(path: Path) -> dict:
    rows = _timings(path)
    if not rows:
        return {"documents": 0}
    seconds = sorted(item["seconds"] for item in rows)
    pages = sum(int(item.get("pages") or 0) for item in rows)
    tables = sum(int(item.get("tables") or 0) for item in rows)
    records = sum(int(item.get("records") or 0) for item in rows)
    extract_ms = sum(
        float((item.get("stages_ms") or {}).get("extract") or 0) for item in rows
    )
    return {
        "documents": len(rows),
        "pages": pages,
        "tables": tables,
        "records": records,
        "total_s": round(sum(seconds), 2),
        "p50_s": round(_percentile(seconds, 0.50), 2),
        "p95_s": round(_percentile(seconds, 0.95), 2),
        "max_s": round(max(seconds), 2),
        "mean_s": round(sum(seconds) / len(seconds), 2),
        "s_per_page": round(sum(seconds) / pages, 3) if pages else None,
        "s_per_table": round(sum(seconds) / tables, 3) if tables else None,
        "docs_per_hour": round(3600 / (sum(seconds) / len(seconds)), 1),
        "extract_share": round(extract_ms / (sum(seconds) * 1000), 4)
        if seconds
        else None,
        "per_document": [
            {
                "doc_id": item["doc_id"],
                "pages": item.get("pages"),
                "tables": item.get("tables"),
                "records": item.get("records"),
                "seconds": item.get("seconds"),
                "extract_s": round(float((item.get("stages_ms") or {}).get("extract") or 0) / 1000, 2),
            }
            for item in sorted(rows, key=lambda row: row["seconds"], reverse=True)
        ],
    }


def _usage(runs: Path) -> dict:
    docs = 0
    model_docs = 0
    prompt = completion = 0
    for trace_path in sorted(runs.glob("*/trace.json")):
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        usage = trace.get("model_usage") or {}
        docs += 1
        if int(usage.get("total_tokens") or 0) > 0:
            model_docs += 1
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
    return {
        "documents_with_trace": docs,
        "model_documents": model_docs,
        "model_documents_rate": round(model_docs / docs, 4) if docs else 0.0,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _quality(runs: Path) -> dict:
    docs = 0
    values = 0
    with_evidence = 0
    silent = 0
    silent_docs = 0
    by_code: Counter[str] = Counter()
    for result_path in sorted(runs.glob("*/result.json")):
        docs += 1
        result = DocumentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        evidence = _load_evidence(result_path.parent / "evidence.jsonl")
        evidence_ids = {item.evidence_id for item in evidence}
        findings = audit_document(result, evidence).findings
        if findings:
            silent_docs += 1
        silent += len(findings)
        for finding in findings:
            by_code[finding.code] += 1
        for record in result.records:
            for value in record.properties.values():
                values += 1
                if value.evidence_id and value.evidence_id in evidence_ids:
                    with_evidence += 1
    return {
        "documents": docs,
        "values": values,
        "values_with_evidence": with_evidence,
        "evidence_rate": round(with_evidence / values, 4) if values else 0.0,
        "silent_errors": silent,
        "silent_documents": silent_docs,
        "by_code": dict(by_code),
    }


AGREEMENT_KEYS = ("comparator", "value", "lower", "upper", "unit", "text")


def _agreement(left: Path, right: Path) -> dict:
    matched = compared = left_only = right_only = 0
    documents = 0
    per_doc = []
    for result_path in sorted(left.glob("*/result.json")):
        doc_id = result_path.parent.name
        other = right / doc_id / "result.json"
        if not other.exists():
            continue
        documents += 1
        left_fields = _fields(result_path)
        right_fields = _fields(other)
        common = set(left_fields) & set(right_fields)
        doc_matched = sum(
            1
            for key in common
            if _signature(left_fields[key]) == _signature(right_fields[key])
        )
        compared += len(common)
        matched += doc_matched
        left_only += len(set(left_fields) - set(right_fields))
        right_only += len(set(right_fields) - set(left_fields))
        per_doc.append(
            {
                "doc_id": doc_id,
                "common": len(common),
                "matched": doc_matched,
                "agreement": round(doc_matched / len(common), 4) if common else None,
                "left_only": len(set(left_fields) - set(right_fields)),
                "right_only": len(set(right_fields) - set(left_fields)),
            }
        )
    union = compared + left_only + right_only
    return {
        "documents": documents,
        "compared_fields": compared,
        "matched": matched,
        "field_agreement": round(matched / compared, 4) if compared else None,
        "jaccard": round(matched / union, 4) if union else None,
        "left_only": left_only,
        "right_only": right_only,
        "per_document": per_doc,
    }


def _fields(path: Path) -> dict[tuple[str, str], object]:
    result = DocumentResult.model_validate_json(path.read_text(encoding="utf-8"))
    fields = {}
    for record in result.records:
        for prop, value in record.properties.items():
            fields[(record.record_id, prop)] = value
    return fields


def _signature(value) -> tuple:
    return tuple(getattr(value, key) for key in AGREEMENT_KEYS)


def _timings(path: Path) -> list[dict]:
    if not path.exists():
        return []
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        latest[item["doc_id"]] = item
    return list(latest.values())


def _load_evidence(path: Path) -> list[Evidence]:
    if not path.exists():
        return []
    return [
        Evidence.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    index = (len(values) - 1) * ratio
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def render(report: dict) -> str:
    accuracy = report.get("accuracy") or {}
    latency = report.get("latency") or {}
    quality = report.get("quality") or {}
    agreement = report.get("agreement") or {}
    lines = [
        "# 抽取准确率与耗时报告",
        "",
        "## 1. 金标准确率",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 文档 | {accuracy.get('documents', 0)} |",
        f"| Record F1 | {accuracy.get('record_f1')} |",
        f"| Field F1 | {accuracy.get('field_f1')} |",
        f"| Value accuracy | {accuracy.get('value_accuracy')} |",
        f"| Evidence rate | {accuracy.get('evidence_rate')} |",
        f"| Coverage | {accuracy.get('coverage_rate')} |",
        f"| 检测项目准确率 | {accuracy.get('inspection_accuracy')} |",
        f"| 分类准确率 | {accuracy.get('classification_accuracy')} |",
        "",
        "## 2. 耗时",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 文档 | {latency.get('documents', 0)} |",
        f"| 页 / 表 | {latency.get('pages', 0)} / {latency.get('tables', 0)} |",
        f"| p50 | {latency.get('p50_s')} s |",
        f"| p95 | {latency.get('p95_s')} s |",
        f"| 均值 / 最大 | {latency.get('mean_s')} s / {latency.get('max_s')} s |",
        f"| 秒/页 | {latency.get('s_per_page')} |",
        f"| 秒/表 | {latency.get('s_per_table')} |",
        f"| 文档/小时 | {latency.get('docs_per_hour')} |",
        f"| 抽取阶段占比 | {latency.get('extract_share')} |",
        f"| 触发模型的文档 | {latency.get('model_documents')}/{latency.get('documents_with_trace')} |",
        f"| Prompt / Completion token | {latency.get('prompt_tokens')} / {latency.get('completion_tokens')} |",
        "",
        "## 3. 证据与静默错误",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 字段值 | {quality.get('values', 0)} |",
        f"| 有证据 | {quality.get('values_with_evidence', 0)}（{quality.get('evidence_rate')}） |",
        f"| silent error | {quality.get('silent_errors', 0)}（{quality.get('silent_documents', 0)} 份） |",
        f"| 错误码 | {json.dumps(quality.get('by_code') or {}, ensure_ascii=False)} |",
        "",
        "## 4. 与 mock 基线一致性",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 文档 | {agreement.get('documents', 0)} |",
        f"| 可比字段 | {agreement.get('compared_fields', 0)} |",
        f"| 完全一致 | {agreement.get('matched', 0)}（{agreement.get('field_agreement')}） |",
        f"| Jaccard | {agreement.get('jaccard')} |",
        "",
        "## 5. 分文档耗时（降序）",
        "",
        "| 文档 | 页 | 表 | 记录 | 秒 | 抽取秒 |",
        "|---|---|---|---|---|---|",
    ]
    for item in latency.get("per_document") or []:
        lines.append(
            f"| {item['doc_id']} | {item['pages']} | {item['tables']} | "
            f"{item['records']} | {item['seconds']} | {item['extract_s']} |"
        )
    if report.get("diverse"):
        diverse = report["diverse"]
        lines.extend(
            [
                "",
                "## 6. 扩展语料抽样（无金标）",
                "",
                "| 指标 | 值 |",
                "|---|---|",
                f"| 文档 | {diverse.get('documents', 0)} |",
                f"| 页 / 表 / 记录 | {diverse.get('pages')} / {diverse.get('tables')} / {diverse.get('records')} |",
                f"| p50 / p95 | {diverse.get('p50_s')} s / {diverse.get('p95_s')} s |",
                f"| 秒/页 / 秒/表 | {diverse.get('s_per_page')} / {diverse.get('s_per_table')} |",
                f"| 证据率 | {(report.get('diverse_quality') or {}).get('evidence_rate')} |",
                f"| silent error | {(report.get('diverse_quality') or {}).get('silent_errors')} |",
            ]
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
