"""Cost per page from replayed runs (M5.2-04).

Money is only computed when ``infra/cost_model.json`` carries non-zero unit
prices; otherwise the report stays in resource units (pages, calls, seconds).
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--model", default=str(ROOT.parent / "infra" / "cost_model.json"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "m5-cost.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "m5-cost.md"))
    args = parser.parse_args(argv)

    rate = json.loads(Path(args.model).read_text(encoding="utf-8"))
    docs: list[dict] = []
    for manifest_path in sorted(Path(args.runs).glob("*/manifest.json")):
        run = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        trace = _read_json(run / "trace.json")
        pages = int(manifest.get("page_count") or 0)
        steps = {step.get("name"): step for step in trace.get("steps", [])}
        ocr_pages = int((steps.get("ocr") or {}).get("pages") or 0)
        extract_calls = 1 if "extract" in steps else 0
        elapsed_ms = float(trace.get("elapsed_ms") or 0.0)
        tokens = int((trace.get("model_usage") or {}).get("total_tokens") or 0)
        docs.append(
            {
                "doc_id": manifest.get("doc_id") or run.name,
                "pages": pages,
                "ocr_pages": ocr_pages,
                "extract_calls": extract_calls,
                "model_tokens": tokens,
                "elapsed_ms": round(elapsed_ms, 2),
                "ms_per_page": round(elapsed_ms / pages, 2) if pages else None,
            }
        )

    pages = sum(doc["pages"] for doc in docs)
    elapsed = sum(doc["elapsed_ms"] for doc in docs)
    calls = sum(doc["extract_calls"] for doc in docs)
    ocr_pages = sum(doc["ocr_pages"] for doc in docs)
    tokens = sum(doc["model_tokens"] for doc in docs)
    per_page_ms = [doc["ms_per_page"] for doc in docs if doc["ms_per_page"]]
    cpu_seconds = elapsed / 1000
    cost = {
        "ocr": ocr_pages * float(rate.get("ocr_per_page") or 0),
        "extract": calls * float(rate.get("extract_per_call") or 0),
        "tokens": tokens / 1000 * float(rate.get("token_per_1k") or 0),
        "cpu": cpu_seconds * float(rate.get("cpu_second") or 0),
    }
    total_cost = sum(cost.values())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": str(Path(args.runs)),
        "rates": rate,
        "totals": {
            "documents": len(docs),
            "pages": pages,
            "ocr_pages": ocr_pages,
            "extract_calls": calls,
            "model_tokens": tokens,
            "elapsed_ms": round(elapsed, 2),
            "cpu_seconds": round(cpu_seconds, 2),
            "ms_per_page": round(elapsed / pages, 2) if pages else None,
            "ms_per_page_p95": round(
                sorted(per_page_ms)[max(0, int(len(per_page_ms) * 0.95) - 1)], 2
            )
            if per_page_ms
            else None,
            "ms_per_page_median": round(statistics.median(per_page_ms), 2)
            if per_page_ms
            else None,
            "cost_total": round(total_cost, 4),
            "cost_per_page": round(total_cost / pages, 4) if pages else None,
            "cost_breakdown": {key: round(value, 4) for key, value in cost.items()},
        },
        "documents": docs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"out={out}")
    return 0


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "# M5 成本核算（每页资源单位）",
        "",
        f"- 文档：{totals['documents']}，页数：{totals['pages']}",
        f"- OCR 页数 / 抽取调用：{totals['ocr_pages']} / {totals['extract_calls']}",
        f"- 模型 token：{totals['model_tokens']}",
        f"- 端到端耗时：{totals['elapsed_ms'] / 1000:.1f}s，CPU 秒：{totals['cpu_seconds']:.1f}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 每页耗时（中位） | {totals['ms_per_page_median']} ms |",
        f"| 每页耗时（p95） | {totals['ms_per_page_p95']} ms |",
        f"| 每页成本 | {totals['cost_per_page']} {report['rates'].get('currency', '')} |",
        f"| 成本拆分 | {totals['cost_breakdown']} |",
        "",
        "## 说明",
        "",
        "- 单价为 0 时只报告资源单位；填 `infra/cost_model.json` 后自动计算金额。",
        "- 模型 token 从 `trace.json` 的 `model_usage` 读取；单价为 0 时只报告 token 数。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
