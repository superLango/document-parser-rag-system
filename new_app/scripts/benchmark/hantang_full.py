#!/usr/bin/env python3
"""汉唐标准全量解析测试。

枚举 ``汉唐标准`` 下六类标准的全部 PDF（默认跳过 >25MB 的大文件），逐份走
上传 -> 建 run -> 轮询 -> 采集记录/字段/审核/诊断的完整链路，运行过程中
增量落盘，便于长时间批量跑完后直接做原文核对。

输出：
* ``--out-json``  每份文档的解析结果与诊断明细（增量写入）
* ``--out-md``    批次汇总报告
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from closeout_e2e import (  # noqa: E402
    MAX_PDF_BYTES,
    REPO_ROOT,
    STANDARD_DIRS,
    now_iso,
    p95,
    percentile,
    run_document,
    sha256_bytes,
    wait_run,
)

DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "hantang-full-runs.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "hantang-full-baseline.md"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_COMMON_CJK = set(
    "的与和及或按应在不为中上下本标准试验方法规定要求材料性能表试样温度时间等图附录第条款规范"
)


def _looks_garbled(text: str) -> bool:
    text = str(text or "")
    if len(text.strip()) < 120:
        return False
    cjk = len(_CJK_RE.findall(text))
    common = sum(1 for char in text if char in _COMMON_CJK)
    if cjk >= 40 and common / cjk < 0.05:
        return True
    control = sum(
        1
        for char in text
        if (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
        or 0xE000 <= ord(char) <= 0xF8FF
    )
    if control / len(text) > 0.01:
        return True
    if cjk == 0:
        symbols = sum(1 for char in text if unicodedata.category(char)[0] in "PS")
        if symbols / len(text) > 0.45:
            return True
    return False


def _pdf_needs_fresh_ocr(path: str) -> bool:
    """True when any page text layer is garbled and must be re-OCR'd."""
    try:
        import pymupdf
    except ImportError:
        return True
    try:
        document = pymupdf.open(path)
    except Exception:  # noqa: BLE001 - unreadable PDF must go through OCR
        return True
    try:
        return any(_looks_garbled(page.get_text() or "") for page in document)
    finally:
        document.close()


def enumerate_pdfs(
    categories: list[str] | None = None,
    max_bytes: int = MAX_PDF_BYTES,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """返回 (待解析列表, 因体积跳过列表)。"""
    selected: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for category, relative in STANDARD_DIRS.items():
        if categories and category not in categories:
            continue
        root = REPO_ROOT / relative
        for path in sorted(root.rglob("*.pdf")):
            size = path.stat().st_size
            if size > max_bytes:
                skipped.append(
                    {"name": path.name, "path": str(path), "bytes": str(size), "category": category}
                )
                continue
            digest = sha256_bytes(path.read_bytes())
            if digest in seen:
                continue
            seen.add(digest)
            selected.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "category": category,
                    "bytes": str(size),
                    "sha256": digest,
                }
            )
    return selected, skipped


def _s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url="http://localhost:19000",
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _read_run(client: httpx.Client, api: str, run_id: str) -> dict[str, Any]:
    run, _ = wait_run(client, api, run_id, timeout=1800)
    stats: dict[str, Any] = {
        "status": run.get("status"),
        "error_code": run.get("error_code"),
        "records": 0,
        "fields": 0,
        "tables": 0,
        "review_status": "",
        "findings": 0,
        "artifacts": 0,
        "review_rules": [],
        "top_findings": [],
        "diagnostics": {},
        "strategy_hits": [],
        "diagnostic_key": "",
    }
    if run.get("status") == "STRUCTURED_READY":
        response = client.get(f"{api}/v1/runs/{run_id}/records")
        if response.status_code == 200:
            records = response.json().get("records") or []
            stats["records"] = len(records)
            stats["fields"] = sum(
                len(record.get("properties") or {}) for record in records if isinstance(record, dict)
            )
        result_response = client.get(f"{api}/v1/runs/{run_id}/result")
        if result_response.status_code == 200:
            stats["tables"] = len((result_response.json().get("result") or {}).get("tables") or [])
    review = client.get(f"{api}/v1/runs/{run_id}/review")
    if review.status_code == 200:
        body = review.json()
        findings = body.get("findings") or []
        stats["review_status"] = body.get("status")
        stats["findings"] = len(findings)
        stats["review_rules"] = sorted(
            {str(finding.get("rule_id")) for finding in findings if isinstance(finding, dict)}
        )
        stats["top_findings"] = [
            {
                "rule_id": finding.get("rule_id"),
                "severity": finding.get("severity"),
                "message": str(finding.get("message") or "")[:160],
            }
            for finding in findings[:5]
            if isinstance(finding, dict)
        ]
    artifacts = client.get(f"{api}/v1/runs/{run_id}/artifacts")
    if artifacts.status_code == 200:
        payload = artifacts.json()
        items = payload.get("value") if isinstance(payload, dict) else payload
        stats["artifacts"] = len(items or [])
        for artifact in items or []:
            if artifact.get("role") == "diagnostics":
                stats["diagnostic_key"] = str(artifact.get("storage_key") or "")
    return stats


def _load_diagnostics(storage_key: str) -> tuple[dict[str, int], list[str]]:
    if not storage_key:
        return {}, []
    try:
        client = _s3_client()
        body = client.get_object(Bucket="hanson-docs", Key=storage_key)["Body"].read()
        entries = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001 - diagnostics are best effort
        return {}, []
    if isinstance(entries, dict):
        entries = entries.get("diagnostics") or []
    counts = Counter(str(entry.get("code")) for entry in entries if isinstance(entry, dict))
    strategies = sorted(
        {
            str((entry.get("detail") or {}).get("strategy"))
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("code") == "STRATEGY_HIT"
            and (entry.get("detail") or {}).get("strategy")
        }
    )
    return dict(counts), strategies


def collect_run(
    api: str,
    item: dict[str, str],
    fresh_after: str = "",
    parser_version: str = "",
) -> dict[str, Any]:
    data = Path(item["path"]).read_bytes()
    with httpx.Client(timeout=3600) as client:
        result = run_document(
            client,
            api,
            name=item["name"],
            data=data,
            content_type="application/pdf",
            timeout=3600,
        )
        result["category"] = item["category"]
        result["bytes"] = int(item["bytes"])
        result["path"] = item["path"]
        result["reparsed"] = False
        run_id = result.get("run_id")
        if not run_id:
            result.update({"review_rules": [], "top_findings": [], "diagnostics": {}, "strategy_hits": []})
            return result

        detail = client.get(f"{api}/v1/runs/{run_id}")
        created = ""
        current_parser = ""
        if detail.status_code == 200:
            created = str(detail.json().get("created_at") or "")
            current_parser = str(detail.json().get("parser_version") or "")
        stale_time = bool(fresh_after and created and created < fresh_after)
        stale_parser = bool(parser_version and current_parser != parser_version)
        if stale_time or stale_parser:
            reuse_ocr = not _pdf_needs_fresh_ocr(item["path"])
            payload = {"parser_version": parser_version, "reuse_ocr": reuse_ocr} if parser_version else {}
            reparse = client.post(f"{api}/v1/runs/{run_id}/reparse", json=payload)
            if reparse.status_code in {200, 201, 202}:
                new_id = reparse.json().get("id")
                if new_id:
                    fresh = _read_run(client, api, new_id)
                    result.update(fresh)
                    result["run_id"] = new_id
                    result["reparsed"] = True
                    run_id = new_id

        stats = _read_run(client, api, run_id)
        for key in (
            "records",
            "fields",
            "tables",
            "review_status",
            "findings",
            "artifacts",
            "review_rules",
            "top_findings",
        ):
            result[key] = stats[key]
        counts, strategies = _load_diagnostics(stats.get("diagnostic_key", ""))
        result["diagnostics"] = counts
        result["strategy_hits"] = strategies
    return result


def summarize(documents: list[dict[str, Any]], skipped: list[dict[str, str]], elapsed: float) -> dict[str, Any]:
    statuses = Counter(item.get("status") or "UNKNOWN" for item in documents)
    durations = [float(item.get("elapsed_seconds") or 0) for item in documents]
    by_category: dict[str, dict[str, Any]] = {}
    for item in documents:
        bucket = by_category.setdefault(
            item.get("category") or "未知",
            {"documents": 0, "structured_ready": 0, "records": 0, "fields": 0, "empty_docs": 0, "seconds": 0.0},
        )
        bucket["documents"] += 1
        bucket["structured_ready"] += int(item.get("status") == "STRUCTURED_READY")
        bucket["records"] += int(item.get("records") or 0)
        bucket["fields"] += int(item.get("fields") or 0)
        bucket["empty_docs"] += int(item.get("status") == "STRUCTURED_READY" and not item.get("records"))
        bucket["seconds"] += float(item.get("elapsed_seconds") or 0)

    total_records = sum(int(item.get("records") or 0) for item in documents)
    ready = statuses.get("STRUCTURED_READY", 0)
    empty = sum(1 for item in documents if item.get("status") == "STRUCTURED_READY" and not item.get("records"))
    diagnostics = Counter()
    for item in documents:
        for code, count in (item.get("diagnostics") or {}).items():
            diagnostics[code] += int(count)
    strategy_docs = Counter()
    for item in documents:
        for strategy in item.get("strategy_hits") or []:
            strategy_docs[strategy] += 1
    return {
        "documents": len(documents),
        "structured_ready": ready,
        "failed": len(documents) - ready,
        "status_counts": dict(sorted(statuses.items())),
        "records": total_records,
        "fields": sum(int(item.get("fields") or 0) for item in documents),
        "tables": sum(int(item.get("tables") or 0) for item in documents),
        "empty_documents": empty,
        "empty_document_rate": round(empty / max(1, ready), 4),
        "review_findings": sum(int(item.get("findings") or 0) for item in documents),
        "docs_with_findings": sum(1 for item in documents if int(item.get("findings") or 0) > 0),
        "skipped_large": len(skipped),
        "skipped_large_names": [item["name"] for item in skipped],
        "p50_seconds": percentile(durations, 0.50),
        "p95_seconds": p95(durations),
        "max_seconds": round(max(durations), 2) if durations else 0.0,
        "total_seconds": round(elapsed, 2),
        "diagnostics": dict(sorted(diagnostics.items())),
        "strategy_documents": dict(sorted(strategy_docs.items())),
        "by_category": by_category,
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    metrics = payload["summary"]
    lines = [
        "# 汉唐标准全量解析基线",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 服务：{payload['api']}；并发：{payload['concurrency']}",
        f"> 样本：{metrics['documents']} 份（跳过 >25MB 大文件 {metrics['skipped_large']} 份）",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 结构化成功 | {metrics['structured_ready']}/{metrics['documents']} |",
        f"| 失败 | {metrics['failed']} |",
        f"| 记录数 | {metrics['records']} |",
        f"| 字段数 | {metrics['fields']} |",
        f"| 零记录文档 | {metrics['empty_documents']}（{metrics['empty_document_rate']:.2%}） |",
        f"| 审核发现数 | {metrics['review_findings']}（涉及 {metrics['docs_with_findings']} 份） |",
        f"| p50 / p95 耗时 | {metrics['p50_seconds']}s / {metrics['p95_seconds']}s |",
        f"| 批次总耗时 | {metrics['total_seconds']}s |",
        "",
        "## 2. 分类别",
        "",
        "| 类别 | 文档 | 结构化成功 | 记录 | 字段 | 零记录 | 耗时(s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for category, bucket in metrics["by_category"].items():
        lines.append(
            f"| {category} | {bucket['documents']} | {bucket['structured_ready']} | "
            f"{bucket['records']} | {bucket['fields']} | {bucket['empty_docs']} | "
            f"{bucket['seconds']:.0f} |"
        )
    lines += ["", "## 3. 策略与诊断", ""]
    if metrics["strategy_documents"]:
        lines.append("| 策略 | 命中文档数 |")
        lines.append("|---|---|")
        for strategy, count in metrics["strategy_documents"].items():
            lines.append(f"| {strategy} | {count} |")
    else:
        lines.append("无策略命中。")
    if metrics["diagnostics"]:
        lines += ["", "| 诊断码 | 次数 |", "|---|---|"]
        for code, count in metrics["diagnostics"].items():
            lines.append(f"| {code} | {count} |")
    lines += ["", "## 4. 零记录文档明细", ""]
    lines.append("| 文档 | 类别 | 页 | 表 | 状态 |")
    lines.append("|---|---|---|---|---|")
    for item in sorted(payload["documents"], key=lambda row: (row.get("category") or "", row["name"])):
        if item.get("status") == "STRUCTURED_READY" and not item.get("records"):
            lines.append(
                f"| {item['name']} | {item.get('category')} | {item.get('pages') or '-'} | "
                f"{item.get('tables') or 0} | {item.get('status')} |"
            )
    if metrics["skipped_large_names"]:
        lines += ["", "## 5. 跳过大文件（>25MB）", ""]
        lines += [f"- {name}" for name in metrics["skipped_large_names"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="0 表示全量")
    parser.add_argument("--category", default="", help="逗号分隔的类别过滤")
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--resume", action="store_true", help="跳过已成功且已有记录的文档")
    parser.add_argument(
        "--fresh-after",
        default="",
        help="ISO 时间；早于该时间创建的 run 会走 reparse 强制重新解析",
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        default=MAX_PDF_BYTES / 1024 / 1024,
        help="单份 PDF 体积上限（MB）；默认 25，传 0 表示不限制",
    )
    parser.add_argument(
        "--parser-version",
        default="",
        help="目标 parser 版本；已有 run 版本不一致时强制 reparse（含重新 OCR）",
    )
    args = parser.parse_args()

    api = args.api.rstrip("/")
    categories = [item.strip() for item in args.category.split(",") if item.strip()]
    max_bytes = int(args.max_mb * 1024 * 1024) if args.max_mb > 0 else 10**12
    pdfs, skipped = enumerate_pdfs(categories or None, max_bytes)
    if args.limit:
        pdfs = pdfs[: args.limit]

    known: dict[str, Any] = {}
    documents: list[dict[str, Any]] = []
    if args.resume and args.out_json.exists():
        previous = json.loads(args.out_json.read_text(encoding="utf-8"))
        documents = list(previous.get("documents") or [])
        known = {item["name"]: item for item in documents}
        pdfs = [
            item
            for item in pdfs
            if not (
                known.get(item["name"], {}).get("status") == "STRUCTURED_READY"
                and known.get(item["name"], {}).get("records")
            )
        ]

    print(f"[hantang] {len(pdfs)} documents, skipped {len(skipped)} large files", flush=True)
    started = time.monotonic()
    checkpoint = args.out_json
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        payload = {
            "generated_at": now_iso(),
            "api": api,
            "concurrency": args.concurrency,
            "summary": summarize(documents, skipped, time.monotonic() - started),
            "documents": sorted(documents, key=lambda row: (row.get("category") or "", row["name"])),
        }
        checkpoint.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {
            pool.submit(
                collect_run, api, item, args.fresh_after, args.parser_version
            ): item
            for item in pdfs
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                documents.append(future.result())
            except Exception as exc:  # noqa: BLE001 - 批次不因单份失败中断
                documents.append(
                    {
                        "name": item["name"],
                        "category": item["category"],
                        "path": item["path"],
                        "status": "ERROR",
                        "error_code": f"{type(exc).__name__}: {exc}"[:200],
                        "records": 0,
                        "fields": 0,
                        "tables": 0,
                        "elapsed_seconds": 0.0,
                    }
                )
            latest = documents[-1]
            flush()
            done = index
            average = (time.monotonic() - started) / done
            eta = average * (len(pdfs) - done)
            print(
                f"[{done}/{len(pdfs)}] {item['name'][:56]} -> {latest.get('status')} "
                f"records={latest.get('records')} fields={latest.get('fields')} "
                f"{float(latest.get('elapsed_seconds') or 0):.1f}s eta={eta / 60:.1f}min",
                flush=True,
            )

    elapsed = time.monotonic() - started
    flush()
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    write_markdown(args.out_md, payload)
    summary = payload["summary"]
    print(
        f"[done] {summary['structured_ready']}/{summary['documents']} ready, "
        f"{summary['records']} records, {summary['empty_documents']} empty docs, "
        f"{summary['total_seconds']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
