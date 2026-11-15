#!/usr/bin/env python3
"""Audit the HT top-30 library: completeness and correctness signals per doc.

Pulls the newest run for every document and reports record/field totals,
category coverage, grade coverage, unit/operator quality and review findings.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "ht-top30-audit.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "ht-top30-audit.md"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
NUMERIC_UNITLESS = {"", "1", "-"}


def _latest_runs(client: httpx.Client, api: str) -> dict[str, dict[str, Any]]:
    response = client.get(f"{api}/v1/runs", params={"limit": 500})
    response.raise_for_status()
    runs = response.json()
    if isinstance(runs, dict):
        runs = runs.get("items") or []
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        document_id = str(run.get("document_id") or "")
        if not document_id:
            continue
        created = str(run.get("created_at") or "")
        if document_id not in latest or created > str(latest[document_id].get("created_at") or ""):
            latest[document_id] = run
    return latest


def _english_leftover(text: str) -> bool:
    text = str(text or "").strip()
    if len(text) < 24 or CJK_RE.search(text):
        return False
    return len(LATIN_RE.findall(text)) >= 18


def audit_document(
    client: httpx.Client, api: str, document: dict[str, Any], run: dict[str, Any]
) -> dict[str, Any]:
    run_id = str(run.get("id") or "")
    detail = client.get(f"{api}/v1/runs/{run_id}").json()
    records: list[dict[str, Any]] = []
    response = client.get(f"{api}/v1/runs/{run_id}/records")
    if response.status_code == 200:
        records = response.json().get("records") or []
    categories: Counter[str] = Counter()
    profiles: Counter[str] = Counter()
    operators: Counter[str] = Counter()
    grades: Counter[str] = Counter()
    measure_fields = 0
    unitless = 0
    english = 0
    placeholder_grades = 0
    evidence_missing = 0
    values_missing = 0
    for record in records:
        profiles[str(record.get("profile") or "unknown")] += 1
        grade = str(record.get("grade") or "").strip()
        grades[grade or "<empty>"] += 1
        if grade in {"", "~", "全部牌号"}:
            placeholder_grades += 1
        if not record.get("evidence_refs"):
            evidence_missing += 1
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            measure_fields += 1
            category = str(prop.get("business_category") or prop.get("feature") or measure)
            categories[category] += 1
            operator = str(prop.get("operator") or "").strip()
            if operator:
                operators[operator] += 1
            if prop.get("value") is None:
                values_missing += 1
            elif str(prop.get("unit") or "").strip() in NUMERIC_UNITLESS:
                unitless += 1
            if _english_leftover(str(prop.get("raw") or "")) or _english_leftover(
                str(prop.get("requirement") or "")
            ):
                english += 1
    review = {"status": "", "findings": 0, "rules": []}
    response = client.get(f"{api}/v1/runs/{run_id}/review")
    if response.status_code == 200:
        body = response.json()
        findings = body.get("findings") or []
        review = {
            "status": body.get("status"),
            "findings": len(findings),
            "rules": sorted({str(item.get("rule_id")) for item in findings}),
        }
    result_meta: dict[str, Any] = {}
    response = client.get(f"{api}/v1/runs/{run_id}/result")
    if response.status_code == 200:
        result = response.json().get("result") or {}
        result_meta = {
            "tables": len(result.get("tables") or []),
            "clauses": len(result.get("clauses") or []),
            "references": len(result.get("references") or []),
        }
        intelligence = result.get("document_intelligence") or {}
        if isinstance(intelligence, dict):
            result_meta["inventory_items"] = len(intelligence.get("inventory") or [])
            coverage = intelligence.get("coverage") or {}
            if isinstance(coverage, dict):
                result_meta["coverage_ratio"] = coverage.get("ratio")
    return {
        "document_id": document.get("id"),
        "filename": document.get("filename"),
        "status": detail.get("status"),
        "parser_version": detail.get("parser_version"),
        "run_id": run_id,
        "records": len(records),
        "fields": measure_fields,
        "profiles": dict(profiles),
        "categories": dict(categories.most_common()),
        "grades": dict(grades.most_common(12)),
        "grade_count": len([grade for grade in grades if grade not in {"", "~", "全部牌号"}]),
        "placeholder_grade_records": placeholder_grades,
        "unitless_numeric": unitless,
        "values_missing": values_missing,
        "english_leftover": english,
        "evidence_missing": evidence_missing,
        "operators": dict(operators),
        "review": review,
        "result": result_meta,
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# HT 标准 Top30 解析复核",
        "",
        f"> 生成时间：{payload['generated_at']}",
        "",
        "## 文档级指标",
        "",
        "| 文档 | 状态 | parser | 记录 | 字段 | 牌号 | 无单位 | 英文残留 | 审核 | 类别 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in payload["documents"]:
        categories = ", ".join(
            f"{name}:{count}" for name, count in list(item["categories"].items())[:8]
        )
        lines.append(
            f"| {item['filename']} | {item['status']} | {item['parser_version']} | "
            f"{item['records']} | {item['fields']} | {item['grade_count']} | "
            f"{item['unitless_numeric']} | {item['english_leftover']} | "
            f"{item['review']['findings']} | {categories} |"
        )
    lines += [
        "",
        "## 合计",
        "",
        f"- 文档：{payload['summary']['documents']}",
        f"- 记录：{payload['summary']['records']}",
        f"- 字段：{payload['summary']['fields']}",
        f"- 审核发现：{payload['summary']['findings']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()
    api = args.api.rstrip("/")
    with httpx.Client(timeout=120) as client:
        documents_response = client.get(f"{api}/v1/documents", params={"limit": 200})
        documents_response.raise_for_status()
        documents = documents_response.json()
        if isinstance(documents, dict):
            documents = documents.get("items") or []
        latest = _latest_runs(client, api)
        rows: list[dict[str, Any]] = []
        for document in documents:
            run = latest.get(str(document.get("id") or ""))
            if not run:
                continue
            rows.append(audit_document(client, api, document, run))
    summary = {
        "documents": len(rows),
        "records": sum(item["records"] for item in rows),
        "fields": sum(item["fields"] for item in rows),
        "findings": sum(item["review"]["findings"] for item in rows),
        "unitless_numeric": sum(item["unitless_numeric"] for item in rows),
        "english_leftover": sum(item["english_leftover"] for item in rows),
        "placeholder_grade_records": sum(item["placeholder_grade_records"] for item in rows),
        "values_missing": sum(item["values_missing"] for item in rows),
    }
    payload = {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "api": api,
        "summary": summary,
        "documents": sorted(rows, key=lambda item: str(item["filename"])),
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
