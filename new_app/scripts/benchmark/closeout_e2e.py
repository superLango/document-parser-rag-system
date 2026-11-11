#!/usr/bin/env python3
"""Closeout end-to-end validation.

Runs three independent suites against the deployed Compose stack:

* ``pdf``      real PDFs from the legacy sample folders (OCR -> routing ->
                 sandbox -> review -> structured output)
* ``legacy``   legacy ``result.json`` tables rebuilt into markdown, which
                 isolates the parser path and feeds the new-vs-old comparison
* ``branches`` API, state-machine and error branches (dedupe, cancel, delete,
                 invalid channel, missing resources, SSE, dictionary, recipes)

The report is written as JSON and Markdown under ``new_app/docs/reports``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_APP = REPO_ROOT / "new_app"
DEFAULT_API = os.getenv("API_BASE", "http://localhost:18000")
DEFAULT_OUT_JSON = NEW_APP / "docs" / "reports" / "closeout-e2e.json"
DEFAULT_OUT_MD = NEW_APP / "docs" / "reports" / "closeout-e2e.md"
FIXTURE = NEW_APP / "tests" / "fixtures" / "mechanical-z.md"
TERMINAL = {"STRUCTURED_READY", "REVIEW_FAILED", "FAILED", "CANCELLED"}
MAX_PDF_BYTES = 25 * 1024 * 1024

STANDARD_DIRS = {
    "国家标准": "汉唐标准/标准1/国家标准（54）",
    "国际标准": "汉唐标准/标准1/国际标准（3）",
    "国军标": "汉唐标准/标准2/国军标（33）",
    "企业标准": "汉唐标准/标准3/企业标准（5）",
    "美国标准": "汉唐标准/标准3/美国标准（83）",
    "行业标准": "汉唐标准/标准3/行业标准（13）",
}
STANDARD_QUOTAS = {
    "国家标准": 8,
    "国军标": 6,
    "美国标准": 8,
    "行业标准": 4,
    "企业标准": 2,
    "国际标准": 2,
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 2)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 2)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pick_even(items: list[Path], count: int) -> list[Path]:
    if len(items) <= count:
        return items
    step = len(items) / count
    return [items[int(index * step)] for index in range(count)]


def select_pdfs(pdf_limit: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(path: Path, category: str) -> None:
        data = path.read_bytes()
        digest = sha256_bytes(data)
        if digest in seen:
            return
        seen.add(digest)
        selected.append(
            {
                "path": str(path),
                "name": path.name,
                "category": category,
                "sha256": digest,
                "bytes": str(len(data)),
            }
        )

    # Legacy purchase specifications / technical agreements first, then a
    # proportional mix of the six standard families.
    reparse_paths = sorted((REPO_ROOT / "data" / "reparse20-20261109").glob("*.pdf"))
    for path in reparse_paths:
        if path.stat().st_size <= MAX_PDF_BYTES:
            add(path, "采购规范/技术协议")

    remaining = max(0, pdf_limit - len(selected)) if pdf_limit else 0
    total_quota = sum(STANDARD_QUOTAS.values())
    if pdf_limit:
        scaled = {
            category: max(1, round(quota / total_quota * remaining))
            for category, quota in STANDARD_QUOTAS.items()
        }
    else:
        scaled = dict(STANDARD_QUOTAS)
    for category, relative in STANDARD_DIRS.items():
        root = REPO_ROOT / relative
        files = [
            path
            for path in sorted(root.glob("*.pdf"))
            if path.stat().st_size <= MAX_PDF_BYTES
        ]
        for path in pick_even(files, scaled[category]):
            add(path, category)
    return selected[:pdf_limit] if pdf_limit else selected


def load_legacy_candidates(limit: int) -> list[dict[str, Any]]:
    from m8_effect_compare import load_candidates

    return load_candidates(
        REPO_ROOT / "data" / "validation-2026-11-06" / "runs" / "full9", limit
    )


def wait_run(
    client: httpx.Client, api: str, run_id: str, timeout: float = 600
) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    run: dict[str, Any] = {}
    while time.monotonic() - started < timeout:
        response = client.get(f"{api}/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run.get("status") in TERMINAL:
            break
        time.sleep(2)
    return run, round(time.monotonic() - started, 2)


def run_document(
    client: httpx.Client,
    api: str,
    *,
    name: str,
    data: bytes,
    content_type: str,
    channel: str = "stable",
    timeout: float = 600,
) -> dict[str, Any]:
    started = time.monotonic()
    upload = client.post(
        f"{api}/v1/documents",
        files={"file": (name, data, content_type)},
    )
    if upload.status_code != 201:
        return {
            "name": name,
            "document_id": "",
            "run_id": "",
            "status": f"UPLOAD_{upload.status_code}",
            "error_code": upload.text[:200],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "records": 0,
            "fields": 0,
            "tables": 0,
            "review_status": "",
            "findings": 0,
            "artifacts": 0,
        }
    document = upload.json()
    created = client.post(
        f"{api}/v1/documents/{document['id']}/runs",
        json={"recipe_channel": channel, "parse_profile": "standard"},
    )
    if created.status_code != 201:
        return {
            "name": name,
            "document_id": document["id"],
            "run_id": "",
            "status": f"RUN_{created.status_code}",
            "error_code": created.text[:200],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "records": 0,
            "fields": 0,
            "tables": 0,
            "review_status": "",
            "findings": 0,
            "artifacts": 0,
        }
    run = created.json()
    run, _ = wait_run(client, api, run["id"], timeout=timeout)
    elapsed = round(time.monotonic() - started, 2)
    payload: dict[str, Any] = {
        "name": name,
        "document_id": document["id"],
        "run_id": run["id"],
        "status": run.get("status"),
        "error_code": run.get("error_code"),
        "elapsed_seconds": elapsed,
        "records": 0,
        "fields": 0,
        "tables": 0,
        "review_status": "",
        "findings": 0,
        "artifacts": 0,
        "stage_ms": {},
    }
    timeline_response = client.get(f"{api}/v1/runs/{run['id']}/timeline")
    if timeline_response.status_code == 200:
        payload["stage_ms"] = {
            str(item.get("stage")): int(item.get("duration_ms") or 0)
            for item in (timeline_response.json() or {}).get("stages") or []
        }
    if run.get("status") == "STRUCTURED_READY":
        result_response = client.get(f"{api}/v1/runs/{run['id']}/result")
        if result_response.status_code == 200:
            result = result_response.json().get("result") or {}
            payload["tables"] = len(result.get("tables") or [])
        records_response = client.get(f"{api}/v1/runs/{run['id']}/records")
        if records_response.status_code == 200:
            records = records_response.json().get("records") or []
            payload["records"] = len(records)
            payload["fields"] = sum(
                len(record.get("properties") or {})
                for record in records
                if isinstance(record, dict)
            )
        review_response = client.get(f"{api}/v1/runs/{run['id']}/review")
        if review_response.status_code == 200:
            review = review_response.json()
            payload["review_status"] = review.get("status")
            payload["findings"] = len(review.get("findings") or [])
        artifacts_response = client.get(f"{api}/v1/runs/{run['id']}/artifacts")
        if artifacts_response.status_code == 200:
            payload["artifacts"] = len(artifacts_response.json() or [])
    return payload


def summarize(docs: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item["status"] for item in docs)
    elapsed = [float(item["elapsed_seconds"]) for item in docs if item["elapsed_seconds"]]
    stages = {}
    for stage in ("ocr", "routing", "sandbox", "review"):
        values = [
            float(item.get("stage_ms", {}).get(stage, 0)) / 1000
            for item in docs
            if item.get("stage_ms", {}).get(stage)
        ]
        stages[stage] = {
            "samples": len(values),
            "p50_seconds": percentile(values, 0.50),
            "p95_seconds": p95(values),
        }
    return {
        "documents": len(docs),
        "structured_ready": statuses.get("STRUCTURED_READY", 0),
        "failed": sum(
            count for status, count in statuses.items() if status not in {"STRUCTURED_READY"}
        ),
        "status_counts": dict(sorted(statuses.items())),
        "records": sum(int(item["records"]) for item in docs),
        "fields": sum(int(item["fields"]) for item in docs),
        "tables": sum(int(item["tables"]) for item in docs),
        "review_findings": sum(int(item["findings"]) for item in docs),
        "p50_seconds": percentile(elapsed, 0.50),
        "p95_seconds": p95(elapsed),
        "max_seconds": round(max(elapsed), 2) if elapsed else 0.0,
        "stages": stages,
    }


def branch_suite(api: str, *, feedback: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any = "") -> None:
        results.append({"branch": name, "ok": bool(ok), "detail": detail})

    fixture_bytes = FIXTURE.read_bytes()
    with httpx.Client(timeout=120) as client:
        def check(name, action):
            try:
                ok, detail = action()
                record(name, ok, detail)
            except Exception as exc:  # noqa: BLE001 - branch failures are reported
                record(name, False, f"{type(exc).__name__}: {exc}")

        check("health_gateway", lambda: (client.get(f"{api}/v1/health").status_code == 200, "200"))
        check(
            "upload_empty_file",
            lambda: (
                client.post(
                    f"{api}/v1/documents",
                    files={"file": ("empty.md", b"", "text/markdown")},
                ).status_code
                == 400,
                "400",
            ),
        )

        upload = client.post(
            f"{api}/v1/documents",
            files={"file": ("closeout-branch.md", fixture_bytes, "text/markdown")},
        )
        upload.raise_for_status()
        document = upload.json()
        duplicate = client.post(
            f"{api}/v1/documents",
            files={"file": ("closeout-branch-copy.md", fixture_bytes, "text/markdown")},
        )
        record(
            "upload_dedupe",
            duplicate.status_code == 201 and duplicate.json()["id"] == document["id"],
            document["id"],
        )

        def invalid_channel() -> tuple[bool, str]:
            response = client.post(
                f"{api}/v1/documents/{document['id']}/runs",
                json={"recipe_channel": "canary", "parse_profile": "standard"},
            )
            return response.status_code == 422, str(response.status_code)

        check("create_run_invalid_channel", invalid_channel)
        check(
            "unknown_document_run",
            lambda: (
                client.post(
                    f"{api}/v1/documents/does-not-exist/runs",
                    json={"recipe_channel": "stable", "parse_profile": "standard"},
                ).status_code
                == 404,
                "404",
            ),
        )
        check(
            "unknown_run_get",
            lambda: (client.get(f"{api}/v1/runs/does-not-exist").status_code == 404, "404"),
        )
        check(
            "unknown_recipe",
            lambda: (client.get(f"{api}/v1/recipes/does-not-exist").status_code == 404, "404"),
        )
        dictionary = client.get(f"{api}/v1/dictionary", params={"limit": 5})
        record(
            "dictionary_query",
            dictionary.status_code == 200 and bool((dictionary.json() or {}).get("entries")),
            str(dictionary.status_code),
        )

        created = client.post(
            f"{api}/v1/documents/{document['id']}/runs",
            json={"recipe_channel": "stable", "parse_profile": "standard"},
        )
        created.raise_for_status()
        run_id = created.json()["id"]
        cancelled = client.post(f"{api}/v1/runs/{run_id}/cancel")
        record(
            "cancel_run",
            cancelled.status_code == 200
            and cancelled.json()["status"] in {"CANCELLED", "STRUCTURED_READY"},
            cancelled.text[:120],
        )
        result = client.get(f"{api}/v1/runs/{run_id}/result")
        record(
            "result_after_cancel",
            result.status_code == 200,
            str(result.status_code),
        )
        record(
            "records_after_cancel",
            client.get(f"{api}/v1/runs/{run_id}/records").status_code == 404,
            "404",
        )

        # A fresh run is used for the happy-path branch checks.
        created = client.post(
            f"{api}/v1/documents/{document['id']}/runs",
            json={"recipe_channel": "stable", "parse_profile": "standard"},
        )
        created.raise_for_status()
        happy_id = created.json()["id"]
        run, _ = wait_run(client, api, happy_id, timeout=300)
        record("happy_path", run.get("status") == "STRUCTURED_READY", run.get("status") or "")

        timeline = client.get(f"{api}/v1/runs/{happy_id}/timeline")
        stages = [item.get("stage") for item in (timeline.json() or {}).get("stages") or []]
        record(
            "timeline_stage_order",
            timeline.status_code == 200 and stages == ["ocr", "routing", "sandbox", "review"],
            stages,
        )

        artifacts = client.get(f"{api}/v1/runs/{happy_id}/artifacts")
        record(
            "artifacts_present",
            artifacts.status_code == 200 and len(artifacts.json() or []) >= 5,
            len(artifacts.json() or []),
        )
        check(
            "missing_page_image",
            lambda: (
                client.get(f"{api}/v1/runs/{happy_id}/pages/999/image").status_code == 404,
                "404",
            ),
        )

        def review_gate() -> tuple[bool, dict]:
            body = (
                "# 审核门禁\n\n<table>"
                "<tr><th>牌号</th><th>抗拉强度Rm/MPa</th></tr>"
                "<tr><td>Q355B</td><td>-10</td></tr>"
                "</table>\n"
            ).encode()
            upload = client.post(
                f"{api}/v1/documents",
                files={"file": ("closeout-review-gate.md", body, "text/markdown")},
            )
            upload.raise_for_status()
            created = client.post(
                f"{api}/v1/documents/{upload.json()['id']}/runs",
                json={"recipe_channel": "stable", "parse_profile": "standard"},
            )
            created.raise_for_status()
            run, _ = wait_run(client, api, created.json()["id"], timeout=300)
            review = client.get(f"{api}/v1/runs/{run['id']}/review")
            detail = {
                "status": run.get("status"),
                "error_code": run.get("error_code"),
                "review": review.json().get("status") if review.status_code == 200 else None,
            }
            ok = (
                run.get("status") == "REVIEW_FAILED"
                and run.get("error_code") == "REVIEW_FAILED"
                and detail["review"] == "fail"
            )
            return ok, detail

        check("review_gate_blocks_deterministic_error", review_gate)

        def sse_events() -> tuple[bool, str]:
            seen: set[str] = set()
            deadline = time.monotonic() + 20
            with client.stream(
                "GET", f"{api}/v1/runs/{happy_id}/events", params={"after": 0}
            ) as response:
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        seen.add(line[7:].strip())
                    if "event: done" in line or time.monotonic() > deadline:
                        break
            ok = "run.stage.started" in seen and "done" in seen
            return ok, sorted(seen)

        check("sse_event_stream", sse_events)

        def delete_with_active_run() -> tuple[bool, str]:
            extra = client.post(
                f"{api}/v1/documents",
                files={
                    "file": (
                        "closeout-delete.md",
                        fixture_bytes + b"\n<!-- delete-branch -->\n",
                        "text/markdown",
                    )
                },
            )
            extra.raise_for_status()
            extra_id = extra.json()["id"]
            run = client.post(
                f"{api}/v1/documents/{extra_id}/runs",
                json={"recipe_channel": "stable", "parse_profile": "standard"},
            )
            run.raise_for_status()
            run_id = run.json()["id"]
            deleted = client.delete(f"{api}/v1/documents/{extra_id}")
            time.sleep(2)
            gone = client.get(f"{api}/v1/documents/{extra_id}")
            final_run = client.get(f"{api}/v1/runs/{run_id}")
            run_status = (
                final_run.json().get("status") if final_run.status_code == 200 else "deleted"
            )
            ok = (
                deleted.status_code == 204
                and gone.status_code == 404
                and (
                    final_run.status_code == 404
                    or run_status in {"CANCELLED", "STRUCTURED_READY"}
                )
            )
            return ok, {
                "delete": deleted.status_code,
                "document": gone.status_code,
                "run": run_status,
            }

        check("delete_document_with_active_run", delete_with_active_run)

        if feedback:
            def feedback_flow() -> tuple[bool, dict]:
                created_feedback = client.post(
                    f"{api}/v1/feedback",
                    json={
                        "run_id": happy_id,
                        "category": "missing_measure",
                        "target": {
                            "recipe_id": "mechanical_properties_v1",
                            "measure": "Re",
                            "unit": "MPa",
                            "family": "tensile",
                        },
                        "description": "屈服强度 Re 未抽取（收尾验证）",
                        "expected_value": "345",
                        "reporter": "closeout-e2e",
                    },
                )
                created_feedback.raise_for_status()
                feedback_id = created_feedback.json()["id"]
                processed = client.post(f"{api}/v1/feedback/{feedback_id}/process")
                processed.raise_for_status()
                body = processed.json()
                detail = {"process_status": body.get("status")}
                if body.get("status") == "verified":
                    rejected = client.post(
                        f"{api}/v1/feedback/{feedback_id}/verify",
                        json={
                            "decision": "reject",
                            "reason": "closeout e2e reject",
                            "actor": "operator",
                        },
                    )
                    rejected.raise_for_status()
                    detail["verify_status"] = rejected.json().get("status")
                    return rejected.json().get("status") == "discarded", detail
                return body.get("status") in {"proposed", "rejected"}, detail

            check("feedback_repair_verify", feedback_flow)

    return results


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# 收尾端到端验证报告",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 环境：{payload['environment']}",
        f"> API：{payload['api']}",
        "",
        "## 1. 汇总",
        "",
        "| 套件 | 文档数 | 成功 | 失败 | 记录数 | 字段数 | p50(s) | p95(s) | max(s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, summary in payload["suites"].items():
        lines.append(
            f"| {name} | {summary['documents']} | {summary['structured_ready']} | "
            f"{summary['failed']} | {summary['records']} | {summary['fields']} | "
            f"{summary['p50_seconds']} | {summary['p95_seconds']} | {summary['max_seconds']} |"
        )
    lines.extend(
        [
            "",
            "### 阶段耗时（秒）",
            "",
            "| 套件 | 阶段 | 样本 | p50 | p95 |",
            "|---|---|---|---|---|",
        ]
    )
    for name, summary in payload["suites"].items():
        for stage, stats in summary.get("stages", {}).items():
            lines.append(
                f"| {name} | {stage} | {stats['samples']} | "
                f"{stats['p50_seconds']} | {stats['p95_seconds']} |"
            )
    lines.extend(
        [
            "",
            "## 2. 文档明细",
            "",
            "| 套件 | 文档 | 类型 | 状态 | 耗时(s) | 表 | 记录 | 字段 | 审核 | 发现 | 产物 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for suite, docs in payload["documents"].items():
        for item in docs:
            lines.append(
                f"| {suite} | {item['name'][:48]} | {item.get('category', '-')} | "
                f"{item['status']} | {item['elapsed_seconds']} | {item['tables']} | "
                f"{item['records']} | {item['fields']} | {item.get('review_status') or '-'} | "
                f"{item['findings']} | {item['artifacts']} |"
            )
    lines.extend(["", "## 3. 分支覆盖", "", "| 分支 | 结果 | 证据 |", "|---|---|---|"])
    for item in payload["branches"]:
        lines.append(
            f"| {item['branch']} | {'通过' if item['ok'] else '失败'} | "
            f"{json.dumps(item['detail'], ensure_ascii=False)[:120]} |"
        )
    failed = [item["branch"] for item in payload["branches"] if not item["ok"]]
    lines.extend(
        [
            "",
            "## 4. 结论",
            "",
            f"- 文档处理：{sum(s['documents'] for s in payload['suites'].values())} 份；"
            f"失败 {sum(s['failed'] for s in payload['suites'].values())} 份。",
            f"- 分支覆盖：{len(payload['branches'])} 项；失败 {len(failed)} 项。",
            f"- 失败分支：{', '.join(failed) if failed else '无'}。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--pdf-limit", type=int, default=50)
    parser.add_argument("--legacy-limit", type=int, default=60)
    parser.add_argument("--pdf-concurrency", type=int, default=2)
    parser.add_argument("--legacy-concurrency", type=int, default=3)
    parser.add_argument("--pdf-only-file", type=Path, default=None)
    parser.add_argument("--suites", default="pdf,legacy,branches")
    parser.add_argument("--feedback", action="store_true")
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()
    api = args.api.rstrip("/")
    suites = {item.strip() for item in args.suites.split(",") if item.strip()}

    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "api": api,
        "environment": "compose（生产镜像）",
        "suites": {},
        "documents": {},
        "branches": [],
    }

    if "pdf" in suites:
        pdfs = select_pdfs(args.pdf_limit)
        if args.pdf_only_file is not None:
            needles = [
                line.strip()
                for line in args.pdf_only_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            pdfs = [
                item
                for item in pdfs
                if any(needle.lower() in item["name"].lower() for needle in needles)
            ]
        print(f"[pdf] {len(pdfs)} documents")
        documents: list[dict[str, Any]] = []

        def run_pdf(item: dict[str, str]) -> dict[str, Any]:
            data = Path(item["path"]).read_bytes()
            with httpx.Client(timeout=900) as client:
                result = run_document(
                    client,
                    api,
                    name=item["name"],
                    data=data,
                    content_type="application/pdf",
                )
            result["category"] = item["category"]
            return result

        with ThreadPoolExecutor(max_workers=max(1, args.pdf_concurrency)) as pool:
            futures = {pool.submit(run_pdf, item): item for item in pdfs}
            for index, future in enumerate(as_completed(futures), start=1):
                item = futures[future]
                try:
                    documents.append(future.result())
                except Exception as exc:  # noqa: BLE001 - keep the suite running
                    documents.append(
                        {
                            "name": item["name"],
                            "category": item["category"],
                            "status": "ERROR",
                            "error_code": f"{type(exc).__name__}: {exc}"[:200],
                            "elapsed_seconds": 0.0,
                            "records": 0,
                            "fields": 0,
                            "tables": 0,
                            "review_status": "",
                            "findings": 0,
                            "artifacts": 0,
                        }
                    )
                print(f"[pdf {index}/{len(pdfs)}] {item['name'][:60]} -> {documents[-1]['status']}")
        documents.sort(key=lambda row: row["name"])
        payload["documents"]["pdf"] = documents
        payload["suites"]["pdf"] = summarize(documents)

    if "legacy" in suites:
        from m8_effect_compare import render_markdown

        candidates = load_legacy_candidates(args.legacy_limit)
        print(f"[legacy] {len(candidates)} documents")

        def run_legacy(item: dict[str, Any]) -> dict[str, Any]:
            markdown = render_markdown(item["result"])
            with httpx.Client(timeout=600) as client:
                result = run_document(
                    client,
                    api,
                    name=f"legacy-{item['doc_id'][:12]}.md",
                    data=markdown.encode("utf-8"),
                    content_type="text/markdown",
                )
            result["category"] = item["dominant"]
            return result

        documents = []
        with ThreadPoolExecutor(max_workers=max(1, args.legacy_concurrency)) as pool:
            futures = {pool.submit(run_legacy, item): item for item in candidates}
            for index, future in enumerate(as_completed(futures), start=1):
                item = futures[future]
                try:
                    documents.append(future.result())
                except Exception as exc:  # noqa: BLE001 - keep the suite running
                    documents.append(
                        {
                            "name": f"legacy-{item['doc_id'][:12]}.md",
                            "category": item["dominant"],
                            "status": "ERROR",
                            "error_code": f"{type(exc).__name__}: {exc}"[:200],
                            "elapsed_seconds": 0.0,
                            "records": 0,
                            "fields": 0,
                            "tables": 0,
                            "review_status": "",
                            "findings": 0,
                            "artifacts": 0,
                        }
                    )
                print(
                    f"[legacy {index}/{len(candidates)}] "
                    f"{item['doc_id'][:12]} -> {documents[-1]['status']}"
                )
        documents.sort(key=lambda row: row["name"])
        payload["documents"]["legacy"] = documents
        payload["suites"]["legacy"] = summarize(documents)

    if "branches" in suites:
        branches = branch_suite(api, feedback=args.feedback)
        payload["branches"] = branches
        print(f"[branches] {sum(1 for item in branches if item['ok'])}/{len(branches)} passed")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.out_md, payload)
    print(
        json.dumps(
            {name: suite for name, suite in payload["suites"].items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(suite["failed"] == 0 for suite in payload["suites"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
