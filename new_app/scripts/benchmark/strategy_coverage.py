#!/usr/bin/env python3
"""Strategy hit-rate statistics on legacy documents that produced zero records.

The M8 comparison harness filters out zero-field documents, so they never show
up in the main metrics. This script re-parses exactly those documents and reads
the sandbox diagnostics (``STRATEGY_HIT``) to answer:

- How many zero-record documents now produce records at all.
- Which strategies (``grade_property_tail`` / ``element_matrix`` / ...) hit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import boto3
import httpx
from m8_effect_compare import (
    DEFAULT_API,
    DEFAULT_OLD_RUNS,
    fields_of,
    new_parse,
    render_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "strategy-coverage.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "strategy-coverage.md"

RECORD_COUNT = re.compile(r"produced (\d+) records")


def object_store():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT", "http://localhost:19000"),
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
        region_name="us-east-1",
    )


def artifact_payload(
    client: httpx.Client, api: str, store: Any, run_id: str, role: str
) -> dict[str, Any]:
    """Read the latest artifact for ``role`` straight from object storage.

    The run result endpoint only exposes the artifact for ``STRUCTURED_READY``
    runs; review-failed runs still keep ``result``/``records``/``diagnostics``
    artifacts, which is exactly what this report needs.
    """
    response = client.get(f"{api}/v1/runs/{run_id}/artifacts")
    if response.status_code != 200:
        return {}
    keys = [
        str(item.get("storage_key") or "")
        for item in response.json() or []
        if item.get("role") == role and item.get("storage_key")
    ]
    if not keys:
        return {}
    body = store.get_object(
        Bucket=os.getenv("OBJECT_STORAGE_BUCKET", "hanson-docs"), Key=keys[-1]
    )["Body"].read()
    payload = json.loads(body.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def zero_record_documents(old_runs: Path, limit: int) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for doc_dir in sorted(old_runs.iterdir()):
        result_path = doc_dir / "run" / "result.json"
        if not result_path.exists():
            continue
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        records = data.get("records") or []
        tables = data.get("tables") or []
        if records or fields_of(records, new=False) or not tables:
            continue
        documents.append({"doc_id": doc_dir.name, "result": data})
        if len(documents) >= limit:
            break
    return documents


def collect(documents: list[dict[str, Any]], api: str) -> dict[str, Any]:
    strategy_docs: Counter[str] = Counter()
    strategy_records: Counter[str] = Counter()
    parser_runs: list[dict[str, Any]] = []
    store = object_store()
    with httpx.Client(timeout=200) as client:
        for item in documents:
            parsed = new_parse(
                client,
                api,
                render_markdown(item["result"]),
                f"{item['doc_id']}.md",
            )
            run_id = parsed["run_id"]
            result = parsed.get("result") or {}
            if not result:
                result = artifact_payload(client, api, store, run_id, "result")
            diagnostics = result.get("diagnostics") or []
            if not diagnostics:
                diagnostics = (
                    artifact_payload(client, api, store, run_id, "diagnostics").get(
                        "diagnostics"
                    )
                    or []
                )
            records = parsed.get("records") or []
            if not records:
                records = (
                    artifact_payload(client, api, store, run_id, "records").get("records")
                    or []
                )
            hits = {
                str(diag.get("detail", {}).get("strategy"))
                for diag in diagnostics
                if diag.get("code") == "STRATEGY_HIT"
            }
            for diag in diagnostics:
                if diag.get("code") != "STRATEGY_HIT":
                    continue
                name = str(diag.get("detail", {}).get("strategy") or "unknown")
                match = RECORD_COUNT.search(str(diag.get("message") or ""))
                strategy_records[name] += int(match.group(1)) if match else 0
            for name in hits:
                strategy_docs[name] += 1
            parser_runs.append(
                {
                    "doc_id": item["doc_id"],
                    "status": parsed["status"],
                    "records": len(records),
                    "strategies": sorted(hits),
                }
            )
    total = len(documents)
    with_hits = sum(1 for run in parser_runs if run["strategies"])
    with_records = sum(1 for run in parser_runs if run["records"])
    return {
        "documents": total,
        "structured_ready": sum(1 for run in parser_runs if run["status"] == "STRUCTURED_READY"),
        "documents_with_strategy_hit": with_hits,
        "documents_with_records": with_records,
        "hit_rate": round(with_hits / total, 4) if total else 0.0,
        "record_recovery_rate": round(with_records / total, 4) if total else 0.0,
        "strategy_documents": dict(strategy_docs),
        "strategy_records": dict(strategy_records),
        "runs": parser_runs,
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# 策略命中率统计（历史 0 记录文档）",
        "",
        f"- 文档数：{payload['documents']}",
        f"- 解析成功：{payload['structured_ready']}",
        f"- 至少命中一个策略的文档：{payload['documents_with_strategy_hit']}"
        f"（{payload['hit_rate']:.2%}）",
        f"- 解析后产出记录的文档：{payload['documents_with_records']}"
        f"（{payload['record_recovery_rate']:.2%}）",
        "",
        "## 策略命中",
        "",
        "| 策略 | 命中文档数 | 产出记录数 |",
        "|---|---|---|",
    ]
    for name, count in sorted(
        payload["strategy_documents"].items(), key=lambda item: -item[1]
    ):
        lines.append(f"| {name} | {count} | {payload['strategy_records'].get(name, 0)} |")
    lines.extend(["", "## 明细", "", "| 文档 | 状态 | 记录数 | 命中策略 |", "|---|---|---|---|"])
    for run in payload["runs"]:
        strategies = ", ".join(run["strategies"]) or "-"
        lines.append(
            f"| {run['doc_id']} | {run['status']} | {run['records']} | {strategies} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--old-runs", type=Path, default=DEFAULT_OLD_RUNS)
    parser.add_argument("--limit", type=int, default=39)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    documents = zero_record_documents(args.old_runs, args.limit)
    if not documents:
        print("no zero-record documents found")
        return 1
    payload = collect(documents, args.api)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.out_md.write_text(render(payload), encoding="utf-8")
    print(
        f"documents={payload['documents']} hit_rate={payload['hit_rate']:.2%} "
        f"record_recovery={payload['record_recovery_rate']:.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
