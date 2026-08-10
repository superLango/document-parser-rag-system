"""Phase 6 评测 CLI（U12 指标集 + 门禁）。

用法：
  python qa/evaluation/evaluate_phase6.py --subset all|smoke [--skip-ocr] [--output-dir DIR]

指标：
- 任务成功率、平均耗时（全量）
- 版面框检出率/误检率（合成 GT，全量 layout）
- 标题层级准确率（OCR 子集，标题文本匹配）
- OCR 页面正确率、表格还原率（OCR 子集）
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_DOC = ROOT / "test_doc"
GT_DIR = Path(__file__).resolve().parent / "ground_truth"
DEFAULT_OUT = Path(__file__).resolve().parent / "reports"

GATES = {
    "task_success_rate": 0.95,
    "layout_recall": 0.80,
    "layout_precision": 0.70,
    "title_accuracy": 0.70,
    "ocr_page_accuracy": 0.85,
    "table_restore_rate": 0.80,
}

OCR_KINDS = {"text", "table", "mixed", "cover", "header"}


def collect_samples(subset: str) -> list[Path]:
    real = sorted(TEST_DOC.glob("*.pdf"))
    generated = sorted((TEST_DOC / "generated").glob("*.pdf")) if (TEST_DOC / "generated").exists() else []
    all_samples = real + generated
    if subset == "smoke":
        return generated[:5] if generated else all_samples[:5]
    return all_samples


def load_gt(pdf: Path) -> dict | None:
    gt = GT_DIR / (pdf.stem + ".json")
    if not gt.exists():
        return None
    try:
        return json.loads(gt.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - GT 损坏时视为无 GT
        return None


def _norm(bbox: list[float], width: float, height: float) -> list[float]:
    return [
        max(0.0, min(1.0, bbox[0] / width)),
        max(0.0, min(1.0, bbox[1] / height)),
        max(0.0, min(1.0, bbox[2] / width)),
        max(0.0, min(1.0, bbox[3] / height)),
    ]


def _block_page_widths(layout: dict) -> dict[int, tuple[float, float]]:
    sizes = {}
    for page in layout.get("pages", []):
        s = page.get("structural", {})
        sizes[page["page_index"]] = (float(s.get("width_pt", 595)), float(s.get("height_pt", 842)))
    return sizes


def evaluate_layout(pdf: Path, gt: dict | None, options: argparse.Namespace) -> dict:
    from app.services.parsekit import ParseOptions, parse_pdf

    data = pdf.read_bytes()
    started = time.monotonic()
    try:
        result = parse_pdf(
            data,
            options=ParseOptions(
                layout_engine="doclayout",
                dpi=200,
                ocr_enabled=False,
            ),
        )
        elapsed = round(time.monotonic() - started, 3)
        layout = result.layout
        metrics: dict = {
            "sample": pdf.name,
            "success": True,
            "elapsed": elapsed,
            "pages": result.stats["pages"],
            "blocks": result.stats["blocks"],
        }
    except Exception as exc:  # noqa: BLE001 - 单样本失败记录不中断
        return {
            "sample": pdf.name,
            "success": False,
            "elapsed": round(time.monotonic() - started, 3),
            "pages": 0,
            "blocks": 0,
            "error": str(exc)[:200],
        }

    # 版面匹配（有 GT）
    if gt and gt.get("layout_blocks"):
        from qa.evaluation.metrics import match_layout_blocks

        sizes = _block_page_widths(layout)
        gt_blocks = []
        for b in gt["layout_blocks"]:
            page = b["page"]
            w, h = sizes.get(page, (595, 842))
            gt_blocks.append(
                {
                    "page": page,
                    "type": b["type"],
                    "bbox": _norm(b["bbox"], w, h),
                }
            )
        pred_blocks = [
            {
                "page": p["page_index"],
                "type": block["type"],
                "bbox": block["bbox"],
            }
            for p in layout["pages"]
            for block in p["blocks"]
            if block["type"] not in ("header", "footer")
        ]
        matched = match_layout_blocks(gt_blocks, pred_blocks, match_mode="center")
        metrics.update(
            {
                "layout_recall": matched["recall"],
                "layout_precision": matched["precision"],
                "layout_tp": matched["tp"],
                "layout_fp": matched["fp"],
                "layout_fn": matched["fn"],
            }
        )
        # 标题块命中（bbox IoU）
        title_gt = [
            {"page": t["page"], "type": "title", "bbox": _norm(t["bbox"], *sizes.get(t["page"], (595, 842)))}
            for t in gt.get("titles", [])
        ]
        title_pred = [
            {"page": p["page_index"], "type": "title", "bbox": b["bbox"]}
            for p in layout["pages"]
            for b in p["blocks"]
            if b["type"] == "title"
        ]
        title_match = match_layout_blocks(title_gt, title_pred, iou_threshold=0.4, match_mode="center")
        metrics["title_block_hit_rate"] = title_match["recall"]
    else:
        metrics["layout_recall"] = None
        metrics["layout_precision"] = None
        metrics["title_block_hit_rate"] = None
    return metrics


def evaluate_ocr(pdf: Path, gt: dict | None) -> dict:
    """OCR 子集：页面正确率/标题准确率/表格还原率。"""
    from app.services.parsekit import ParseOptions, parse_pdf

    metrics: dict = {"sample": pdf.name, "ocr_pages": 0, "ocr_correct_pages": 0, "titles": 0, "titles_hit": 0, "tables": 0, "tables_ok": 0}
    try:
        result = parse_pdf(
            pdf.read_bytes(),
            options=ParseOptions(layout_engine="doclayout", dpi=100, ocr_enabled=True),
        )
    except Exception as exc:  # noqa: BLE001 - OCR 评测失败记录不中断
        metrics["error"] = str(exc)[:200]
        return metrics
    layout = result.layout

    if not gt:
        return metrics

    from qa.evaluation.metrics import (
        page_correct,
        table_restore_ok,
        text_coverage,
        text_similarity,
    )

    # 按页拼接文本参考与预测
    gt_text_by_page: dict[int, str] = {}
    for t in gt.get("texts", []):
        gt_text_by_page[t["page"]] = gt_text_by_page.get(t["page"], "") + " " + t["text"]
    pred_text_by_page: dict[int, str] = {}
    for p in layout["pages"]:
        pred_text_by_page[p["page_index"]] = " ".join(
            b.get("content", "")
            for b in p["blocks"]
            if b["type"] in ("text", "aside_text", "footnote")
        )
    for page_no in sorted(set(gt_text_by_page) & set(pred_text_by_page)):
        metrics["ocr_pages"] += 1
        coverage = text_coverage(gt_text_by_page[page_no], pred_text_by_page[page_no])
        if page_correct(coverage):
            metrics["ocr_correct_pages"] += 1

    # 标题匹配（页面 + 文本相似度；used 按 (page, idx) 避免跨页冲突）
    used: set[tuple[int, int]] = set()
    for title in gt.get("titles", []):
        page_no = title.get("page", 0)
        if page_no not in pred_text_by_page:
            continue
        page_blocks = next(
            (p["blocks"] for p in layout["pages"] if p["page_index"] == page_no),
            [],
        )
        best = 0.0
        best_idx = -1
        for idx, block in enumerate(page_blocks):
            if block["type"] != "title" or (page_no, idx) in used:
                continue
            sim = text_similarity(title["text"], block.get("content", ""))
            if sim > best:
                best = sim
                best_idx = idx
        metrics["titles"] += 1
        if best >= 0.9 and best_idx >= 0:
            used.add((page_no, best_idx))
            metrics["titles_hit"] += 1

    # 表格还原
    for table in gt.get("tables", []):
        page_blocks = next(
            (p["blocks"] for p in layout["pages"] if p["page_index"] == table["page"]),
            [],
        )
        content = "".join(
            b.get("content", "") for b in page_blocks if b["type"] == "table"
        )
        metrics["tables"] += 1
        if table_restore_ok(content, table["text"]):
            metrics["tables_ok"] += 1
    return metrics


def rate(num: int, den: int) -> float | None:
    return num / den if den else None


def aggregate(layout_metrics: list[dict], ocr_metrics: list[dict]) -> dict:
    """layout_metrics 每样本一条（任务成功率/版面），ocr_metrics 单独汇总。"""
    success = [m for m in layout_metrics if m.get("success")]
    layout_recalls = [m["layout_recall"] for m in success if m.get("layout_recall") is not None]
    layout_precisions = [m["layout_precision"] for m in success if m.get("layout_precision") is not None]
    title_hits = [m["title_block_hit_rate"] for m in success if m.get("title_block_hit_rate") is not None]
    ocr_pages = sum(m.get("ocr_pages", 0) for m in ocr_metrics)
    ocr_correct = sum(m.get("ocr_correct_pages", 0) for m in ocr_metrics)
    titles = sum(m.get("titles", 0) for m in ocr_metrics)
    titles_hit = sum(m.get("titles_hit", 0) for m in ocr_metrics)
    tables = sum(m.get("tables", 0) for m in ocr_metrics)
    tables_ok = sum(m.get("tables_ok", 0) for m in ocr_metrics)
    elapsed = [m.get("elapsed", 0) for m in success]
    return {
        "samples_total": len(layout_metrics),
        "samples_success": len(success),
        "task_success_rate": rate(len(success), len(layout_metrics)),
        "avg_elapsed": round(statistics.mean(elapsed), 3) if elapsed else None,
        "layout_recall": round(statistics.mean(layout_recalls), 4) if layout_recalls else None,
        "layout_precision": round(statistics.mean(layout_precisions), 4) if layout_precisions else None,
        "title_block_hit_rate": round(statistics.mean(title_hits), 4) if title_hits else None,
        "ocr_page_accuracy": rate(ocr_correct, ocr_pages),
        "table_restore_rate": rate(tables_ok, tables),
        "title_accuracy": rate(titles_hit, titles),
    }


def check_gates(agg: dict) -> dict:
    gates = {}
    for name, threshold in GATES.items():
        value = agg.get(name)
        if value is None:
            gates[name] = {"threshold": threshold, "value": None, "pass": None, "note": "N/A（无足够样本）"}
            continue
        gates[name] = {"threshold": threshold, "value": value, "pass": bool(value >= threshold)}
    return gates


def write_report(agg: dict, gates: dict, samples: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "metrics": agg,
        "gates": gates,
        "samples": samples,
    }
    json_path = output_dir / "phase6_metrics.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Phase 6 评测报告", ""]
    lines.append("## 汇总指标")
    lines.append("| 指标 | 值 | 门禁阈值 | 判定 |")
    lines.append("|---|---|---|--|")
    for name, gate in gates.items():
        value = gate["value"] if gate["value"] is not None else "N/A"
        verdict = "通过" if gate["pass"] else ("N/A" if gate["pass"] is None else "未达标")
        lines.append(f"| {name} | {value} | {gate['threshold']} | {verdict} |")
    lines.append("")
    lines.append("## 样本明细")
    lines.append("| 样本 | 成功 | 耗时(s) | 页数 | 版面块 | recall | precision |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in samples:
        if "ocr_pages" in s:
            continue
        lines.append(
            f"| {s['sample']} | {'是' if s.get('success') else '否'} | {s.get('elapsed')} | "
            f"{s.get('pages')} | {s.get('blocks')} | {s.get('layout_recall')} | {s.get('layout_precision')} |"
        )
    md_path = output_dir / "phase6_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 6 评测")
    parser.add_argument("--subset", choices=("all", "smoke"), default="all")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUT
    out_dir = out_dir.resolve()
    allowed = Path(__file__).resolve().parent.resolve()
    if str(out_dir) != str(allowed) and not str(out_dir).startswith(str(allowed) + "/"):
        print(f"错误：输出目录必须位于 {allowed} 内", file=sys.stderr)
        return 2

    samples = collect_samples(args.subset)
    if not samples:
        print("错误：未找到评测样本（test_doc/ 或 test_doc/generated/ 为空）", file=sys.stderr)
        return 2

    layout_metrics: list[dict] = []
    ocr_metrics: list[dict] = []
    for pdf in samples:
        gt = load_gt(pdf)
        layout_metrics.append(evaluate_layout(pdf, gt, args))
        if not args.skip_ocr and gt and gt.get("kind") in OCR_KINDS and gt.get("pages", 99) <= 5:
            ocr_metrics.append(evaluate_ocr(pdf, gt))

    agg = aggregate(layout_metrics, ocr_metrics)
    gates = check_gates(agg)
    md = write_report(agg, gates, layout_metrics + ocr_metrics, out_dir)
    print(json.dumps({"metrics": agg, "gates": gates}, ensure_ascii=False, indent=2))
    print(f"报告已输出：{md}")
    all_pass = all(g["pass"] is not False for g in gates.values())
    print("门禁结论：PASS" if all_pass else "门禁结论：FAIL（详见报告调优项）")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
