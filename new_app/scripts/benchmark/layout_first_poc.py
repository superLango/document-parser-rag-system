#!/usr/bin/env python3
"""Phase-0 PoC: measure layout-first table block detection on zero-record PDFs."""

from __future__ import annotations

import argparse
import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS = REPO_ROOT / "new_app" / "docs" / "reports" / "closeout-standards-e2e.json"
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "layout-first-poc.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "layout-first-poc.md"
DEFAULT_API = "http://192.168.188.75:9978"


def zero_record_docs(path: Path, limit: int) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    docs = [item for item in payload["documents"]["pdf"] if item.get("records", 0) == 0]
    docs.sort(key=lambda item: item.get("tables", 0))
    return docs[:limit]


def analyze_pdf(path: Path, api: str, *, dpi: int, max_pages: int) -> dict:
    document = pymupdf.open(path)
    started = time.monotonic()
    pages = []
    table_blocks = []
    total_blocks = 0
    errors = []
    try:
        for index, page in enumerate(document, start=1):
            if index > max_pages:
                break
            image = page.get_pixmap(dpi=dpi).tobytes("png")
            width, height = float(page.rect.width), float(page.rect.height)
            payload = {
                "page_index": index,
                "width": width,
                "height": height,
                "dpi": dpi,
                "image_base64": base64.b64encode(image).decode("ascii"),
            }
            try:
                response = httpx.post(f"{api}/v1/layout", json=payload, timeout=180)
                response.raise_for_status()
                body = response.json()
            except Exception as exc:  # noqa: BLE001 - keep the PoC running
                errors.append({"page_no": index, "error": str(exc)[:200]})
                continue
            blocks = body.get("blocks") or []
            total_blocks += len(blocks)
            page_tables = [
                {
                    "page_no": index,
                    "bbox": block.get("bbox"),
                    "confidence": block.get("confidence"),
                }
                for block in blocks
                if block.get("type") == "table"
            ]
            table_blocks.extend(page_tables)
            pages.append(
                {
                    "page_no": index,
                    "blocks": len(blocks),
                    "tables": len(page_tables),
                    "types": sorted({str(block.get("type")) for block in blocks}),
                }
            )
    finally:
        document.close()
    elapsed = time.monotonic() - started
    return {
        "pages": pages,
        "blocks": total_blocks,
        "table_blocks": table_blocks,
        "pages_with_tables": sum(1 for page in pages if page["tables"]),
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    docs = zero_record_docs(args.runs, args.limit)
    results = []
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{args.api}/healthz").json()
    for index, item in enumerate(docs, start=1):
        print(f"[{index}/{len(docs)}] {item['name'][:60]}")
        metrics = analyze_pdf(
            Path(item["path"]), args.api, dpi=args.dpi, max_pages=args.max_pages
        )
        results.append(
            {
                "name": item["name"],
                "category": item.get("category"),
                "native_tables": item.get("tables", 0),
                **metrics,
            }
        )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "api": args.api,
        "health": health,
        "documents": results,
        "summary": {
            "documents": len(results),
            "with_table_blocks": sum(1 for item in results if item["table_blocks"]),
            "table_blocks": sum(len(item["table_blocks"]) for item in results),
            "pages_with_tables": sum(item["pages_with_tables"] for item in results),
            "errors": sum(len(item["errors"]) for item in results),
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Phase 0 版面优先 PoC",
        "",
        f"> 生成时间：{payload['generated_at']}",
        f"> 版面服务：`{args.api}`",
        f"> 模型：`{health.get('model_dir')}` / `{health.get('device')}`",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 文档数 | {payload['summary']['documents']} |",
        f"| 检出 table block 的文档 | {payload['summary']['with_table_blocks']} |",
        f"| table block 总数 | {payload['summary']['table_blocks']} |",
        f"| 有表的页数 | {payload['summary']['pages_with_tables']} |",
        f"| 推理错误 | {payload['summary']['errors']} |",
        "",
        "## 2. 文档明细",
        "",
        "| 文档 | 原生表数 | 页数 | blocks | table blocks | 有表页 | 耗时(s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['name'][:44]} | {item['native_tables']} | {len(item['pages'])} | "
            f"{item['blocks']} | {len(item['table_blocks'])} | {item['pages_with_tables']} | "
            f"{item['elapsed_seconds']} |"
        )
    lines.extend(
        [
            "",
            "## 3. 结论",
            "",
            "PoC 只验证版面模型能否发现正文 table block，不验证表格 OCR 内容；"
            "GLM-OCR 恢复后，table block 裁剪图会进入表格 OCR 并生成 HTML。",
        ]
    )
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
