#!/usr/bin/env python3
"""M8 light load test for the Compose stack.

Scenarios: document list, run list, upload, run creation, result queries and a
small agent task. The load is intentionally modest so the single model server
and sandbox host are not saturated.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API = os.getenv("API_BASE", "http://localhost:18000")
DEFAULT_AGENT = os.getenv("AGENT_INTERNAL", "http://localhost:18003")
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "M8-loadtest.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "M8-loadtest.md"
FIXTURE = REPO_ROOT / "new_app" / "tests" / "fixtures" / "mechanical-z.md"
TERMINAL = {"STRUCTURED_READY", "REVIEW_FAILED", "FAILED", "CANCELLED"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index] * 1000, 2)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index] * 1000, 2)


def run_parallel(
    label: str,
    total: int,
    concurrency: int,
    action: Callable[[int], int],
) -> dict[str, Any]:
    latencies: list[float] = []
    errors = 0
    started = time.monotonic()

    def wrapped(index: int) -> tuple[float, int]:
        begin = time.monotonic()
        try:
            status = action(index)
        except Exception:  # noqa: BLE001 - counted as a failed request
            status = 0
        return time.monotonic() - begin, status

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(wrapped, index) for index in range(total)]
        for future in as_completed(futures):
            elapsed, status = future.result()
            latencies.append(elapsed)
            if status < 200 or status >= 300:
                errors += 1

    duration = time.monotonic() - started
    return {
        "scenario": label,
        "requests": total,
        "concurrency": concurrency,
        "errors": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "throughput_rps": round(total / duration, 2) if duration else 0.0,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": p95(latencies),
        "max_ms": round(max(latencies) * 1000, 2) if latencies else 0.0,
        "duration_seconds": round(duration, 2),
    }


def find_completed_run(client: httpx.Client, api: str) -> str:
    response = client.get(f"{api}/v1/runs")
    response.raise_for_status()
    for run in response.json():
        if run.get("status") == "STRUCTURED_READY":
            return str(run["id"])
    raise RuntimeError("no completed run found")


def ensure_fixture_document(
    client: httpx.Client, api: str, suffix: str = ""
) -> str:
    data = FIXTURE.read_bytes() + suffix.encode()
    response = client.post(
        f"{api}/v1/documents",
        files={"file": (FIXTURE.name, data, "text/markdown")},
    )
    response.raise_for_status()
    return str(response.json()["id"])


def wait_run(client: httpx.Client, api: str, run_id: str, timeout: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"{api}/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run.get("status") in TERMINAL:
            return run
        time.sleep(1)
    return run


def percentile_ms(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 2)


def pipeline_stats(
    client: httpx.Client, api: str, run_ids: list[str]
) -> dict[str, Any]:
    """并发跑完后的流水线结果：成功率与 OCR/沙箱阶段耗时。"""
    statuses: Counter[str] = Counter()
    stage_ms: dict[str, list[float]] = defaultdict(list)
    for run_id in run_ids:
        run = wait_run(client, api, run_id)
        statuses[str(run.get("status") or "UNKNOWN")] += 1
        timeline = client.get(f"{api}/v1/runs/{run_id}/timeline")
        if timeline.status_code >= 300:
            continue
        for stage in timeline.json().get("stages") or []:
            duration = stage.get("duration_ms")
            if duration:
                stage_ms[str(stage.get("stage"))].append(float(duration))
    succeeded = statuses.get("STRUCTURED_READY", 0)
    total = sum(statuses.values())
    return {
        "runs": total,
        "succeeded": succeeded,
        "success_rate": round(succeeded / total, 4) if total else 0.0,
        "statuses": dict(statuses),
        "stages": {
            name: {
                "count": len(values),
                "p50_ms": percentile_ms(values, 0.50),
                "p95_ms": percentile_ms(values, 0.95),
            }
            for name, values in sorted(stage_ms.items())
        },
    }


def scan_stats(
    client: httpx.Client, api: str, fixture: Path | None
) -> dict[str, Any]:
    """扫描件成功率：需要显式提供扫描件 PDF，未提供时标记不可用。"""
    if fixture is None or not fixture.exists():
        return {"available": False, "note": "no scan fixture provided"}
    data = fixture.read_bytes()
    uploaded = client.post(
        f"{api}/v1/documents",
        files={"file": (fixture.name, data, "application/pdf")},
    )
    uploaded.raise_for_status()
    run = client.post(
        f"{api}/v1/documents/{uploaded.json()['id']}/runs",
        json={"recipe_channel": "stable"},
    )
    run.raise_for_status()
    final = wait_run(client, api, str(run.json()["id"]))
    timeline = client.get(f"{api}/v1/runs/{run.json()['id']}/timeline").json()
    ocr = next(
        (
            item
            for item in timeline.get("stages") or []
            if item.get("stage") == "ocr"
        ),
        {},
    )
    return {
        "available": True,
        "fixture": fixture.name,
        "status": final.get("status"),
        "success": final.get("status") == "STRUCTURED_READY",
        "ocr_ms": ocr.get("duration_ms"),
    }


def agent_task(index: int) -> dict[str, Any]:
    return {
        "task_id": f"m8-load-{index}",
        "trace_id": f"m8-load-trace-{index}",
        "role": "triage",
        "objective": "Classify the feedback root cause.",
        "inputs": {
            "feedback": {
                "category": "missing_measure",
                "target": {"measure": "Z"},
                "description": "断面收缩率 Z 未抽取",
                "expected_value": "22",
            },
            "run": {"status": "STRUCTURED_READY", "records": 2, "tables": 1},
            "recipe": {"recipe_id": "mechanical_properties_v1", "version": "1.0.1"},
        },
        "output_schema": {},
        "tools": [],
        "budget": {
            "max_steps": 2,
            "max_tool_calls": 0,
            "max_tokens": 8000,
            "wall_time_seconds": 120,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--run-count", type=int, default=6)
    parser.add_argument("--run-concurrency", type=int, default=3)
    parser.add_argument("--scan-fixture", type=Path, default=None)
    args = parser.parse_args()
    api = args.api.rstrip("/")
    agent = args.agent.rstrip("/")

    shares_headers = {"X-Operator": "loadtest", "Idempotency-Key": "loadtest"}

    with httpx.Client(timeout=300) as client:
        run_id = find_completed_run(client, api)
        run_documents = [
            ensure_fixture_document(client, api, f"\n<!-- run {index} -->")
            for index in range(args.run_count)
        ]

        def documents_list(index: int) -> int:
            return client.get(f"{api}/v1/documents").status_code

        def runs_list(index: int) -> int:
            return client.get(f"{api}/v1/runs").status_code

        def upload(index: int) -> int:
            data = FIXTURE.read_bytes()
            return client.post(
                f"{api}/v1/documents",
                files={"file": (FIXTURE.name, data, "text/markdown")},
                headers=shares_headers,
            ).status_code

        run_ids: list[str] = []

        def create_run(index: int) -> int:
            response = client.post(
                f"{api}/v1/documents/{run_documents[index]}/runs",
                json={"recipe_channel": "stable", "parse_profile": "standard"},
                headers=shares_headers,
            )
            if response.status_code == 201:
                run_ids.append(response.json()["id"])
            return response.status_code

        endpoints = ["result", "records", "timeline"]

        def result_query(index: int) -> int:
            return client.get(f"{api}/v1/runs/{run_id}/{endpoints[index % 3]}").status_code

        def agent_call(index: int) -> int:
            return client.post(
                f"{agent}/internal/agent:run",
                json=agent_task(index),
                headers=shares_headers,
            ).status_code

        scenarios = [
            run_parallel("documents_list", 50, 5, documents_list),
            run_parallel("runs_list", 50, 5, runs_list),
            run_parallel("upload_dedupe", 20, 5, upload),
            run_parallel("create_run", args.run_count, args.run_concurrency, create_run),
        ]

        pipeline = pipeline_stats(client, api, list(run_ids))
        scan = scan_stats(client, api, args.scan_fixture)
        scenarios.append(run_parallel("result_query", 60, 5, result_query))
        scenarios.append(run_parallel("agent_triage", 2, 1, agent_call))

    failures = sum(item["errors"] for item in scenarios)
    totals = sum(item["requests"] for item in scenarios)
    p95_values = [item["p95_ms"] for item in scenarios if item["scenario"] != "create_run"]
    payload = {
        "generated_at": now_iso(),
        "api": api,
        "agent": agent,
        "scenarios": scenarios,
        "pipeline": pipeline,
        "scan": scan,
        "summary": {
            "requests": totals,
            "errors": failures,
            "error_rate": round(failures / totals, 4) if totals else 0.0,
            "max_p95_ms": max(p95_values) if p95_values else 0.0,
            "create_run_ids": run_ids,
            "pipeline_success_rate": pipeline["success_rate"],
            "scan_success": scan.get("success") if scan.get("available") else None,
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    for item in scenarios:
        print(
            f"{item['scenario']}: n={item['requests']} err={item['error_rate']} "
            f"p50={item['p50_ms']}ms p95={item['p95_ms']}ms rps={item['throughput_rps']}"
        )
    return 0 if payload["summary"]["error_rate"] <= 0.01 else 1


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# M8 性能压测报告",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 环境：Compose（{payload['api']}）",
        f"> 结论：错误率 {payload['summary']['error_rate']:.2%}；最大场景 p95 {payload['summary']['max_p95_ms']:.0f} ms",  # noqa: E501
        "",
        "## 1. 场景结果",
        "",
        "| 场景 | 请求数 | 并发 | 错误率 | p50 (ms) | p95 (ms) | max (ms) | RPS |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in payload["scenarios"]:
        lines.append(
            f"| {item['scenario']} | {item['requests']} | {item['concurrency']} | "
            f"{item['error_rate']:.2%} | {item['p50_ms']:.0f} | {item['p95_ms']:.0f} | "
            f"{item['max_ms']:.0f} | {item['throughput_rps']:.2f} |"
        )
    pipeline = payload.get("pipeline") or {}
    scan = payload.get("scan") or {}
    lines.extend(
        [
            "",
            "## 2. 流水线成功率与阶段耗时",
            "",
            f"- 运行数 {pipeline.get('runs', 0)}，成功 {pipeline.get('succeeded', 0)}，"
            f"成功率 {pipeline.get('success_rate', 0):.2%}",
            f"- 终态分布：{json.dumps(pipeline.get('statuses') or {}, ensure_ascii=False)}",
            "",
            "| 阶段 | 样本 | p50 (ms) | p95 (ms) |",
            "|---|---|---|---|",
        ]
    )
    for name, item in (pipeline.get("stages") or {}).items():
        lines.append(
            f"| {name} | {item['count']} | {item['p50_ms']:.0f} | {item['p95_ms']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## 3. 扫描件成功率",
            "",
            (
                f"- {scan.get('fixture')}：status={scan.get('status')} "
                f"success={scan.get('success')} ocr={scan.get('ocr_ms')}ms"
                if scan.get("available")
                else f"- 不可用：{scan.get('note', 'no scan fixture provided')}"
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## 4. 说明",
            "",
            "- 上传场景使用同一文件，按 sha256 去重，主要衡量网关/上传链路开销。",
            f"- 创建 run 场景并发 {payload['scenarios'][3]['concurrency']}，"
            "包含 OCR→路由→沙箱→审核完整链路；result_query 在运行完成后执行。",
            "- Agent 场景调用 triage 角色 2 次，包含真实模型调用，未做高并发，避免压垮单模型服务。",
            "- 扫描件成功率需要 `--scan-fixture` 指定扫描件 PDF，未提供时标记不可用。",
            "- 压测为单机 Compose，非生产规格；结论用于发现明显瓶颈，不作为容量承诺。",
            "",
            "## 5. 结果查询目标",
            "",
            f"- 已完成运行查询使用既有 STRUCTURED_READY 运行（{payload['scenarios'][-2]['scenario']}）。",  # noqa: E501
            f"- 新建运行：{', '.join(payload['summary']['create_run_ids']) or '无'}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
