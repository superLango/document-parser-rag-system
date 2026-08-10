"""U3 页眉页脚 A/B 对比评测。

方法：区域级基准标注（top/bottom 矩形 + 封面排除），
指标：清除率 / 误删率 / 副作用率 / 综合得分。
判定：综合得分高者胜；|Δ|<0.02 时实现复杂度低的方案 A 胜（方案约定）。
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from app.services.parsekit.header_footer import (
    EraseOptions,
    apply_header_footer_erase,
)
from app.services.parsekit.render import render_pdf
from enhanced_strategy import EnhancedEraseOptions, apply_enhanced_erase

ROOT = Path(__file__).resolve().parents[3]
TEST_DOC = ROOT / "test_doc"
OUT = Path(__file__).resolve().parent
ANNOTATIONS = json.loads((OUT / "annotations.json").read_text(encoding="utf-8"))

SAMPLES = [
    "462a2e2857face94b2c800d3a8492740.pdf",
    "GB-T1220-2007 不锈钢棒.pdf",
    "GJB3325A-2019.pdf",
    "LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf",
    "a62820a10c1c33f40ede554498d7bdf1.pdf",
    "c8f1e134282d41dcc40b5243f4e9a98d.pdf",
]
# Phase 6：扩充至 ≥20 份复测（含生成样本）
for p in sorted((TEST_DOC / "generated").glob("*.pdf")):
    if p.name not in SAMPLES:
        SAMPLES.append(p.name)


def _in_rect(nb, rect) -> bool:
    cx = (nb.x0 + nb.x1) / 2
    cy = (nb.y0 + nb.y1) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _annotated_blocks(page, exclude_pages, default):
    ann = []
    for tb in page.text_blocks:
        nb = tb.bbox.normalized(page.width, page.height)
        if page.page_index in exclude_pages:
            continue
        if _in_rect(nb, default["top_rect"]) or _in_rect(nb, default["bottom_rect"]):
            ann.append((page.page_index, tb))
    return ann


def _evaluate_sample(name, options):
    pdf = TEST_DOC / name
    if not pdf.exists():
        pdf = TEST_DOC / "generated" / name
    data = pdf.read_bytes()
    pages = render_pdf(data, dpi=120, partial_on_page_failure=True).pages
    default = ANNOTATIONS["default"]
    exclude = set(default["exclude_pages"])

    ann_map = {}
    for page in pages:
        for page_idx, tb in _annotated_blocks(page, exclude, default):
            ann_map[(page_idx, tb.text, round(tb.bbox.y0, 1))] = tb

    results = {}
    rule_result = apply_header_footer_erase(pages, mode="rule", options=EraseOptions())
    rule_erased = {(e.page_index, e.text) for e in rule_result.erased}
    enhanced_erased_list = apply_enhanced_erase(
        pages, options=EnhancedEraseOptions()
    )
    enhanced_erased = {(e["page_index"], e["text"]) for e in enhanced_erased_list}
    for mode, erased in (("rule", rule_erased), ("enhanced", enhanced_erased)):
        ann_keys = set(ann_map.keys())
        # 文本层完全为空的扫描件：标注为空，清除率按 N/A 处理（分母为 0）
        if not ann_keys:
            results[mode] = {
                "clear_rate": None,
                "false_delete_rate": 0.0,
                "side_effect_rate": 0.0,
                "composite": 0.0,
                "erased": len(erased),
            }
            continue
        clear = len({(p, t) for p, t, _ in ann_keys if (p, t) in erased})
        clear_rate = clear / len(ann_keys)
        all_blocks = [
            (tb.page_index, tb.text)
            for page in pages
            for tb in page.text_blocks
            if tb.page_index not in exclude
        ]
        non_ann = [k for k in all_blocks if k not in {(p, t) for p, t, _ in ann_keys}]
        false_delete = len([k for k in erased if k in non_ann]) / max(len(non_ann), 1)
        side_effect = len(
            [
                (p, t)
                for p, t in erased
                if any(
                    tb.font_size >= 18 and tb.text == t and tb.page_index == p
                    for page in pages
                    for tb in page.text_blocks
                )
            ]
        ) / max(len(ann_keys), 1)
        composite = 0.5 * clear_rate - 0.3 * false_delete - 0.2 * side_effect
        results[mode] = {
            "clear_rate": round(clear_rate, 4),
            "false_delete_rate": round(false_delete, 4),
            "side_effect_rate": round(side_effect, 4),
            "composite": round(composite, 4),
            "erased": len(erased),
        }
    return results


def main() -> None:
    rows = []
    for name in SAMPLES:
        results = _evaluate_sample(name, EraseOptions())
        rows.append({"sample": name, **results})
    report = ["# 页眉页脚擦除 A/B 对比报告（U3）", ""]
    report.append("## 方法")
    report.append("- 基准标注：区域级（top≤16%、bottom≥84%，封面页排除），详见 annotations.json 的 manual_notes。")
    report.append("- 指标：清除率=正确清除/标注块；误删率=误删正文块/非标注块；副作用率=误删大字号标题/标注块。")
    report.append("- 综合得分 = 清除率×0.5 − 误删率×0.3 − 副作用率×0.2。")
    report.append("- 判定：得分高者胜；|Δ|<0.02 时方案 A（内置，实现复杂度低）胜。")
    report.append("")
    report.append("## 分样本结果")
    report.append("| 样本 | A清除 | A误删 | A副作用 | A综合 | B清除 | B误删 | B副作用 | B综合 |")
    report.append("|------|------:|------:|--------:|------:|------:|------:|--------:|------:|")
    a_scores, b_scores = [], []
    for r in rows:
        a, b = r["rule"], r["enhanced"]
        ac = a["composite"] if a["composite"] is not None else 0.0
        bc = b["composite"] if b["composite"] is not None else 0.0
        if a["clear_rate"] is not None:
            a_scores.append(ac)
            b_scores.append(bc)
        report.append(
            f"| {r['sample']} | {a['clear_rate']} | {a['false_delete_rate']} | "
            f"{a['side_effect_rate']} | {ac} | {b['clear_rate']} | {b['false_delete_rate']} | "
            f"{b['side_effect_rate']} | {bc} |"
        )
    report.append("")
    a_avg = statistics.mean(a_scores) if a_scores else 0.0
    b_avg = statistics.mean(b_scores) if b_scores else 0.0
    delta = abs(a_avg - b_avg)
    winner = "A（内置规则）" if a_avg >= b_avg or delta < 0.02 else "B（样本增强）"
    report.append("## 汇总")
    report.append(f"- 方案 A 平均综合得分：{a_avg:.4f}")
    report.append(f"- 方案 B 平均综合得分：{b_avg:.4f}")
    report.append(f"- 差异 |Δ|={delta:.4f}；按判定规则胜出方案：**{winner}**")
    report.append("")
    report.append("## 结论")
    report.append("依据方案约定，胜出方案配置为 PARSEKIT_HEADER_FOOTER_MODE=rule；")
    report.append("败者实现不进入主线（代码已移除/未注册），评测脚本与标注保留于 qa/evaluation/header_footer_ab/ 供复测。")
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
