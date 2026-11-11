#!/usr/bin/env python3
"""Compare the new pipeline against legacy result.json baselines.

Both sides start from the same table grids: the legacy tables are rendered back
to HTML markdown, uploaded to the new API, and the resulting records are
compared field by field with the legacy records.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OLD_RUNS = REPO_ROOT / "data" / "validation-2026-11-06" / "runs" / "full9"
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "M8-effect-comparison.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "M8-effect-comparison.md"
DEFAULT_API = os.getenv("API_BASE", "http://localhost:18000")
TERMINAL = {"STRUCTURED_READY", "REVIEW_FAILED", "FAILED", "CANCELLED"}

ELEMENTS = {
    "C", "Si", "Mn", "P", "S", "Ni", "Cr", "Mo", "Cu", "Al", "Ti", "V", "Nb",
    "N", "O", "H", "B", "W", "Co", "Zr", "Ta", "Re", "Fe", "Sn", "As", "Pb",
    "Sb", "Bi", "Ca", "Mg", "Zn", "Ce", "La", "Y", "Nd", "Se", "Te", "Ag",
}
MECHANICAL = {
    "RM", "RP0.2", "RP1.0", "A", "Z", "KU2", "KV2", "KU5", "HB", "HBW",
    "HRC", "HRB", "HV", "RE", "REL",
}
THRESHOLDS = {
    "field_f1": 0.80,
    "value_match": 0.90,
    "silent_error_rate": 0.05,
    "coverage": 0.90,
    "p95_seconds": 120.0,
}


def now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")").replace("≤", "<=").replace("≥", ">=")
    text = text.replace("～", "~").replace("－", "-")
    return re.sub(r"\s+", "", text)


def normalize_measure(value: str) -> str:
    text = str(value or "").strip()
    if text.upper() in MECHANICAL:
        return text.upper()
    return text


def normalize_grade(value: Any) -> str:
    text = str(value or "").strip()
    return text.upper() if text else "~"


def prop_value(prop: dict[str, Any] | None) -> tuple[float | None, str]:
    if not isinstance(prop, dict):
        return None, ""
    raw = normalize_text(prop.get("raw"))
    value = prop.get("value")
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        number = None
    return number, raw or normalize_text(value)


def fields_of(records: list[dict[str, Any]], *, new: bool) -> dict[tuple[str, str], dict[str, Any]]:
    fields: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        grade = normalize_grade(record.get("grade"))
        condition = condition_of(record, new=new)
        if grade in ("", "~") and condition:
            # Legacy rows without a grade often carry the facet in
            # ``condition``; the new pipeline stores it in ``conditions``.
            grade = normalize_text(condition)
        properties = record.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        for measure, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            key = (grade, normalize_measure(str(measure)))
            if key in fields:
                continue
            number, text = prop_value(prop)
            fields[key] = {
                "value": number,
                "text": text,
                "raw": str(prop.get("raw") or ""),
                "unit": str(prop.get("unit") or ""),
                "record_id": str(record.get("record_id") or ""),
            }
    return fields


def condition_of(record: dict[str, Any], *, new: bool) -> str:
    if new:
        conditions = record.get("conditions") or {}
        if not isinstance(conditions, dict):
            return ""
        return "/".join(
            sorted(normalize_text(value) for value in conditions.values() if value)
        )
    return normalize_text(record.get("condition") or "")


def same_value(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["value"] is not None and right["value"] is not None:
        return math.isclose(float(left["value"]), float(right["value"]), rel_tol=1e-6, abs_tol=1e-9)
    return left["text"] == right["text"]


def family_of(measure: str) -> str:
    upper = measure.upper()
    if upper in ELEMENTS:
        return "chemical"
    if upper in MECHANICAL:
        return "mechanical"
    if re.fullmatch(r"[A-Z][a-z]?", measure):
        return "chemical"
    return "other"


def render_markdown(old: dict[str, Any]) -> str:
    document = old.get("document") or {}
    title = str(document.get("title") or document.get("file_name") or "旧结果")
    lines = [f"# {title}", ""]
    tables = old.get("tables") or []
    for index, table in enumerate(tables, start=1):
        caption = str(table.get("caption") or "").strip()
        lines.append(f"表{index} {caption}".strip())
        header_rows = int(table.get("header_rows") or 1)
        rows = table.get("rows") or []
        lines.append("<table>")
        for row_index, row in enumerate(rows):
            tag = "th" if row_index < header_rows else "td"
            cells = "".join(
                f"<{tag}>{escape_cell(cell)}</{tag}>" for cell in row
            )
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</table>")
        lines.append("")
    return "\n".join(lines)


def escape_cell(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def load_candidates(old_runs: Path, limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_titles: set[str] = set()
    for doc_dir in sorted(old_runs.iterdir()):
        result_path = doc_dir / "run" / "result.json"
        if not result_path.exists():
            continue
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        document = data.get("document") or {}
        content_hash = str(document.get("sha256") or doc_dir.name)
        raw_title = str(document.get("title") or doc_dir.name.split("__")[0]).lower()
        title_key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", raw_title)
        if content_hash in seen_hashes or any(
            title_key in seen or seen in title_key for seen in seen_titles if seen and title_key
        ):
            continue
        records = data.get("records") or []
        tables = data.get("tables") or []
        fields = fields_of(records, new=False)
        # Exclude whole-handbook dumps: they dominate micro metrics and are not
        # representative of a single standard document.
        if len(fields) < 10 or not tables or len(tables) > 80 or len(fields) > 2500:
            continue
        seen_hashes.add(content_hash)
        seen_titles.add(title_key)
        family_counts = Counter(family_of(measure) for _, measure in fields)
        dominant = family_counts.most_common(1)[0][0]
        candidates.append(
            {
                "doc_id": doc_dir.name,
                "result": data,
                "records": records,
                "fields": fields,
                "tables": len(tables),
                "field_count": len(fields),
                "dominant": dominant,
            }
        )

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sorted(candidates, key=lambda row: row["field_count"], reverse=True):
        buckets[item["dominant"]].append(item)

    selected: list[dict[str, Any]] = []
    per_bucket = max(1, math.ceil(limit / max(1, len(buckets))))
    for family in ("chemical", "mechanical", "other"):
        selected.extend(buckets.get(family, [])[:per_bucket])
    if len(selected) < limit:
        seen = {item["doc_id"] for item in selected}
        for item in sorted(candidates, key=lambda row: row["field_count"], reverse=True):
            if item["doc_id"] in seen:
                continue
            selected.append(item)
            seen.add(item["doc_id"])
            if len(selected) >= limit:
                break
    return selected[:limit]


def new_parse(client: httpx.Client, api: str, markdown: str, name: str) -> dict[str, Any]:
    started = time.monotonic()
    upload = client.post(
        f"{api}/v1/documents",
        files={"file": (name, markdown.encode("utf-8"), "text/markdown")},
    )
    upload.raise_for_status()
    document = upload.json()
    created = client.post(
        f"{api}/v1/documents/{document['id']}/runs",
        json={"recipe_channel": "stable", "parse_profile": "standard"},
    )
    created.raise_for_status()
    run = created.json()
    run_id = run["id"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"{api}/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] in TERMINAL:
            break
        time.sleep(1)
    elapsed = time.monotonic() - started
    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    if run["status"] == "STRUCTURED_READY":
        response = client.get(f"{api}/v1/runs/{run_id}/records")
        if response.status_code == 200:
            records = response.json().get("records") or []
        response = client.get(f"{api}/v1/runs/{run_id}/result")
        if response.status_code == 200:
            result = (response.json() or {}).get("result") or {}
    return {
        "run_id": run_id,
        "status": run["status"],
        "error_code": run.get("error_code"),
        "elapsed_seconds": round(elapsed, 2),
        "records": records,
        "result": result,
    }


def compare_doc(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_fields = old["fields"]
    new_fields = fields_of(new["records"], new=True)
    common = set(old_fields) & set(new_fields)
    only_old = set(old_fields) - set(new_fields)
    only_new = set(new_fields) - set(old_fields)
    matches = sum(1 for key in common if same_value(old_fields[key], new_fields[key]))
    silent = len(common) - matches
    precision = len(common) / len(new_fields) if new_fields else 0.0
    recall = len(common) / len(old_fields) if old_fields else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    evidence_records = sum(
        1
        for record in new["records"]
        if isinstance(record, dict) and record.get("evidence_refs")
    )
    recipes = (new.get("result") or {}).get("recipes") or []
    return {
        "doc_id": old["doc_id"],
        "run_id": new["run_id"],
        "status": new["status"],
        "error_code": new.get("error_code"),
        "elapsed_seconds": new["elapsed_seconds"],
        "old_fields": len(old_fields),
        "new_fields": len(new_fields),
        "common_fields": len(common),
        "only_old": len(only_old),
        "only_new": len(only_new),
        "value_matches": matches,
        "value_match_rate": round(matches / len(common), 4) if common else 0.0,
        "silent_errors": silent,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "new_records": len(new["records"]),
        "evidence_rate": round(evidence_records / len(new["records"]), 4)
        if new["records"]
        else 0.0,
        "recipes": recipes,
        "dominant": old["dominant"],
        "tables": old["tables"],
        "examples_only_old": sorted(f"{grade}/{measure}" for grade, measure in only_old)[:8],
        "examples_only_new": sorted(f"{grade}/{measure}" for grade, measure in only_new)[:8],
    }


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 2)


def aggregate(docs: list[dict[str, Any]]) -> dict[str, Any]:
    total_old = sum(item["old_fields"] for item in docs)
    total_new = sum(item["new_fields"] for item in docs)
    total_common = sum(item["common_fields"] for item in docs)
    total_matches = sum(item["value_matches"] for item in docs)
    precision = total_common / total_new if total_new else 0.0
    recall = total_common / total_old if total_old else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    covered = sum(1 for item in docs if item["new_fields"] > 0)
    metrics = {
        "documents": len(docs),
        "old_fields": total_old,
        "new_fields": total_new,
        "common_fields": total_common,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "field_f1": round(f1, 4),
        "value_match_rate": round(total_matches / total_common, 4) if total_common else 0.0,
        "silent_errors": total_common - total_matches,
        "silent_error_rate": round((total_common - total_matches) / total_common, 4)
        if total_common
        else 0.0,
        "coverage": round(covered / len(docs), 4) if docs else 0.0,
        "p95_seconds": p95([item["elapsed_seconds"] for item in docs]),
        "evidence_rate": round(
            statistics.mean([item["evidence_rate"] for item in docs]), 4
        )
        if docs
        else 0.0,
        "failed_runs": sum(1 for item in docs if item["status"] != "STRUCTURED_READY"),
    }
    passed = (
        metrics["field_f1"] >= THRESHOLDS["field_f1"]
        and metrics["value_match_rate"] >= THRESHOLDS["value_match"]
        and metrics["silent_error_rate"] <= THRESHOLDS["silent_error_rate"]
        and metrics["coverage"] >= THRESHOLDS["coverage"]
        and metrics["p95_seconds"] <= THRESHOLDS["p95_seconds"]
    )
    metrics["thresholds"] = THRESHOLDS
    metrics["verdict"] = "pass" if passed else "below_target"
    return metrics


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    lines = [
        "# M8 新旧效果对比报告",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 样本：{metrics['documents']} 份（旧结果表重建为输入）",
        f"> 结论：**{'达标' if metrics['verdict'] == 'pass' else '未达标'}**",
        "",
        "## 1. 指标",
        "",
        "| 指标 | 结果 | 门槛 |",
        "|---|---|---|",
        f"| Field F1 | {metrics['field_f1']:.4f} | ≥ {THRESHOLDS['field_f1']:.2f} |",
        f"| Value match | {metrics['value_match_rate']:.4f} | ≥ {THRESHOLDS['value_match']:.2f} |",
        f"| 静默错误率 | {metrics['silent_error_rate']:.4f} | ≤ {THRESHOLDS['silent_error_rate']:.2f} |",  # noqa: E501
        f"| 覆盖率 | {metrics['coverage']:.4f} | ≥ {THRESHOLDS['coverage']:.2f} |",
        f"| p95 延迟 | {metrics['p95_seconds']:.2f}s | ≤ {THRESHOLDS['p95_seconds']:.2f}s |",
        f"| 证据命中率 | {metrics['evidence_rate']:.4f} | 参考 |",
        f"| 失败运行 | {metrics['failed_runs']} | 0 |",
        "",
        f"- 旧字段：{metrics['old_fields']}；新字段：{metrics['new_fields']}；共同字段：{metrics['common_fields']}",  # noqa: E501
        f"- Precision {metrics['precision']:.4f} / Recall {metrics['recall']:.4f}",
        "",
        "## 2. 文档明细",
        "",
        "| 文档 | 类型 | 旧字段 | 新字段 | 共同 | 值匹配 | F1 | 静默错误 | 耗时(s) | 状态 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in payload["documents"]:
        lines.append(
            "| {doc} | {family} | {old} | {new} | {common} | {match:.2f} | {f1:.3f} | {silent} | {elapsed:.1f} | {status} |".format(  # noqa: E501
                doc=item["doc_id"][:12],
                family=item["dominant"],
                old=item["old_fields"],
                new=item["new_fields"],
                common=item["common_fields"],
                match=item["value_match_rate"],
                f1=item["f1"],
                silent=item["silent_errors"],
                elapsed=item["elapsed_seconds"],
                status=item["status"],
            )
        )
    lines.extend(
        [
            "",
            "## 3. 差异样例",
            "",
            "```text",
        ]
    )
    for item in payload["documents"]:
        lines.append(f"{item['doc_id'][:12]} 仅旧: {', '.join(item['examples_only_old'])}")
        lines.append(f"{item['doc_id'][:12]} 仅新: {', '.join(item['examples_only_new'])}")
    lines.extend(
        [
            "```",
            "",
            "## 4. 说明",
            "",
            "- 两侧使用同一份表结构：旧 `result.json` 的 tables 重建为 HTML 后输入新系统，OCR/版面识别差异不在本样本内。",  # noqa: E501
            "- 字段键为 `(grade, measure)`；同一键重复时取首条。",
            "- 数值比较优先使用解析后的 value（1e-6 容差），缺失时比较归一化 raw。",
            "- 结论用于 Q4 数据导入门禁：达标不导入旧文档；未达标输出差异清单并确认导入范围。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-runs", type=Path, default=DEFAULT_OLD_RUNS)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()
    api = args.api.rstrip("/")

    candidates = load_candidates(args.old_runs, args.limit)
    if not candidates:
        print("no comparable documents found")
        return 1

    def process(item: dict[str, Any]) -> dict[str, Any]:
        markdown = render_markdown(item["result"])
        name = f"m8-compare-{item['doc_id'][:12]}.md"
        try:
            with httpx.Client(timeout=180) as client:
                new = new_parse(client, api, markdown, name)
        except Exception as exc:  # noqa: BLE001 - recorded in the report
            new = {
                "run_id": "",
                "status": "ERROR",
                "error_code": str(exc)[:200],
                "elapsed_seconds": 0.0,
                "records": [],
                "result": {},
            }
        return compare_doc(item, new)

    docs: list[dict[str, Any]] = []
    if args.concurrency <= 1:
        for index, item in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] {item['doc_id'][:12]} fields={item['field_count']}")
            docs.append(process(item))
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(process, item): item for item in candidates
            }
            for index, future in enumerate(as_completed(futures), start=1):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - keep the batch running
                    result = compare_doc(
                        item,
                        {
                            "run_id": "",
                            "status": "ERROR",
                            "error_code": str(exc)[:200],
                            "elapsed_seconds": 0.0,
                            "records": [],
                            "result": {},
                        },
                    )
                print(f"[{index}/{len(candidates)}] {item['doc_id'][:12]} done")
                docs.append(result)
        docs.sort(key=lambda row: row["doc_id"])

    payload = {
        "generated_at": now_iso(),
        "api": args.api,
        "old_runs": str(args.old_runs),
        "metrics": aggregate(docs),
        "documents": docs,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
