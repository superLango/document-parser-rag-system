"""Phase 6 合成评测样本生成器。

生成 14+ 份企业风格 PDF 到 test_doc/generated/（不入 Git），
并输出 ground truth 到 qa/evaluation/ground_truth/（入库）。
每份 GT 含 layout_blocks（page/type/bbox）与 titles/tables/texts 参考。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

A4_W, A4_H = 595, 842
CJK = "china-s"
LATIN = "helv"
GT_DIR = Path(__file__).resolve().parent / "ground_truth"


def _box(x0, y0, x1, y1):
    return [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]


def _add_title(page, x, y, text, level, manifest, page_no):
    size = {1: 24, 2: 17, 3: 13.5}[min(level, 3)]
    page.insert_text((x, y), text, fontsize=size, fontname=CJK)
    width = size * len(text)
    bbox = _box(x, y - size, x + width, y + 4)
    manifest["layout_blocks"].append(
        {"page": page_no, "type": "title", "bbox": bbox}
    )
    manifest["titles"].append(
        {"text": text, "page": page_no, "level": level, "bbox": bbox}
    )
    return bbox


def _add_paragraph(page, rect, text, manifest, page_no, fontsize=12):
    """逐行插入文本，每 3 行一个版面块并记录精确 bbox（贴近模型检测框）。"""
    x0, y0, x1, _ = rect
    chars_per_line = max(1, int((x1 - x0 - 8) / (fontsize * 1.0)))
    lines = [text[i : i + chars_per_line] for i in range(0, len(text), chars_per_line)]
    line_h = fontsize * 1.5
    y = y0
    first_y = y
    for line in lines:
        page.insert_text((x0, y), line, fontsize=fontsize, fontname=CJK)
        y += line_h
    bbox = _box(x0, first_y - line_h + 4, x1, y + 2)
    manifest["layout_blocks"].append(
        {"page": page_no, "type": "text", "bbox": bbox}
    )
    manifest["texts"].append(
        {"text": " ".join(lines), "page": page_no, "bbox": bbox}
    )


def _add_table(page, x, y, rows, cols, width, row_h, manifest, page_no, title=None):
    row_h = max(row_h, 22)
    height = rows * row_h
    bbox = _box(x, y, x + width, y + height)
    cell_w = width / cols
    for r in range(rows + 1):
        page.draw_line((x, y + r * row_h), (x + width, y + r * row_h), color=(0, 0, 0), width=1.0)
    for c in range(cols + 1):
        page.draw_line((x + c * cell_w, y), (x + c * cell_w, y + height), color=(0, 0, 0), width=1.0)
    cell_texts = []
    for r in range(rows):
        row_texts = []
        for c in range(cols):
            text = f"{chr(65 + c)}{r + 1}"
            page.insert_text(
                (x + c * cell_w + 6, y + r * row_h + 14),
                text,
                fontsize=10,
                fontname=LATIN,
            )
            row_texts.append(text)
        cell_texts.append("\t".join(row_texts))
    table_text = "\n".join(cell_texts)
    manifest["layout_blocks"].append(
        {"page": page_no, "type": "table", "bbox": bbox}
    )
    manifest["tables"].append({"text": table_text, "page": page_no, "bbox": bbox, "title": title})
    return bbox


def _add_formula_image(page, rect, latex, manifest, page_no):
    img = Image.new("RGB", (int(rect[2] - rect[0]), int(rect[3] - rect[1])), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), latex, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(pymupdf.Rect(*rect), stream=buf.getvalue())
    manifest["layout_blocks"].append(
        {"page": page_no, "type": "formula", "bbox": list(rect)}
    )
    return list(rect)


def _add_image_block(page, rect, manifest, page_no, caption=None, color=(180, 220, 200)):
    img = Image.new("RGB", (int(rect[2] - rect[0]), int(rect[3] - rect[1])), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, img.width - 10, img.height - 10], outline=(80, 120, 110), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(pymupdf.Rect(*rect), stream=buf.getvalue())
    manifest["layout_blocks"].append(
        {"page": page_no, "type": "image", "bbox": list(rect)}
    )
    if caption:
        cap_bbox = _box(rect[0], rect[3], rect[2], rect[3] + 18)
        page.insert_text((rect[0], rect[3] + 14), caption, fontsize=10, fontname=CJK)
        manifest["layout_blocks"].append(
            {"page": page_no, "type": "image_caption", "bbox": cap_bbox}
        )
    return list(rect)


def _header_footer(page, page_no, total, manifest, header="江苏合盛材料有限公司 内部文件", footer="第 X 页 共 Y 页", complex_mode=False):
    if complex_mode:
        page.insert_text((60, 42), header, fontsize=9.5, fontname=CJK)
        page.insert_text((330, 42), f"文件编号: HS-2026-{page_no:03d}", fontsize=9, fontname=CJK)
    else:
        page.insert_text((60, 42), header, fontsize=10, fontname=CJK)
    page.insert_text((60, 820), footer.replace("X", str(page_no)).replace("Y", str(total)), fontsize=9.5, fontname=CJK)
    manifest["header_footers"].append(
        {"text": header, "page": page_no, "role": "header", "bbox": _box(55, 30, 540, 48)}
    )
    manifest["header_footers"].append(
        {"text": footer, "page": page_no, "role": "footer", "bbox": _box(55, 808, 540, 826)}
    )


def _new_doc():
    return pymupdf.open()


def _save(doc, name, manifest):
    path = Path(__file__).resolve().parents[2] / "test_doc" / "generated" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    manifest["sample"] = name
    manifest["pages"] = manifest["_pages"]
    manifest.pop("_pages", None)
    gt_path = GT_DIR / (name.replace(".pdf", ".json"))
    gt_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 1 单栏文本 ----------
def gen_text_single():
    doc = _new_doc()
    manifest = {"kind": "text", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest)
        if pno == 1:
            _add_title(page, 80, 90, "第一章 材料检验通则", 1, manifest, pno)
            _add_title(page, 90, 135, "1.1 适用范围", 2, manifest, pno)
            _add_paragraph(page, (90, 160, 520, 260), "本标准适用于公司内部金属材料入厂检验，覆盖化学成分、力学性能与表面质量三类检验项目。", manifest, pno)
        elif pno == 2:
            _add_title(page, 80, 90, "1.2 检验项目", 2, manifest, pno)
            _add_paragraph(page, (90, 120, 520, 220), "化学成分按 GB/T 223 系列方法执行；力学性能按 GB/T 228.1 执行；表面质量采用目视与涡流探伤相结合。", manifest, pno)
        else:
            _add_title(page, 80, 90, "1.3 判定规则", 2, manifest, pno)
            _add_paragraph(page, (90, 120, 520, 200), "任一检验项目不合格，判定该批次不合格，并按规定进行复验。", manifest, pno)
    _save(doc, "synth_text_single.pdf", manifest)


# ---------- 2 双栏 ----------
def gen_text_two_column():
    doc = _new_doc()
    manifest = {"kind": "text", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest)
        _add_title(page, 80, 90, {1: "第二章 术语与定义", 2: "第三章 引用标准", 3: "第四章 检验方法"}[pno], 1, manifest, pno)
        for col, x in ((0, 80), (1, 310)):
            _add_paragraph(
                page,
                (x, 130, x + 190, 700),
                (
                    "左栏正文：术语定义与引用标准说明，用于双栏版面阅读顺序评测，"
                    "包含足够文本以支撑版面检测与阅读顺序验证。"
                    if col == 0
                    else "右栏正文：引用标准、检验方法说明，内容完整且排版与左栏对齐。"
                ),
                manifest,
                pno,
            )
    _save(doc, "synth_text_two_column.pdf", manifest)


# ---------- 3 跨页表格 ----------
def gen_table_crosspage():
    doc = _new_doc()
    manifest = {"kind": "table", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest)
        _add_title(page, 80, 90, "附录A 检验记录表（跨页）", 1, manifest, pno) if pno == 1 else None
        _add_table(page, 80, 130, 34, 4, 430, 18, manifest, pno, title=f"检验记录表-第{pno}页")
    _save(doc, "synth_table_crosspage.pdf", manifest)


# ---------- 4 表格+正文混合 ----------
def gen_table_mixed():
    doc = _new_doc()
    manifest = {"kind": "table", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest)
        _add_title(page, 80, 90, "3 力学性能汇总", 1, manifest, pno) if pno == 1 else None
        _add_paragraph(
                page,
                (80, 130, 520, 260),
                "下表为各批次力学性能实测值汇总，供质量判定使用。数据来自实验室检测系统，已按批号、牌号与规格分类归档，确保可追溯。",
                manifest,
                pno,
            )
        _add_table(page, 80, 210, 10, 4, 440, 20, manifest, pno)
    _save(doc, "synth_table_mixed.pdf", manifest)


# ---------- 5 公式 ----------
def gen_formula():
    doc = _new_doc()
    manifest = {"kind": "formula", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 2}
    for pno in range(1, 3):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 2, manifest)
        _add_title(page, 80, 90, f"4 计算公式（第 {pno} 页）", 1, manifest, pno)
        _add_formula_image(page, (90, 140, 420, 200), f"sigma = F / A  (page {pno})", manifest, pno)
        _add_paragraph(page, (90, 230, 520, 300), "式中：σ 为抗拉强度，F 为最大试验力，A 为原始横截面积。", manifest, pno)
    _save(doc, "synth_formula.pdf", manifest)


# ---------- 6 图片+图注 ----------
def gen_image_caption():
    doc = _new_doc()
    manifest = {"kind": "image", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 2}
    for pno in range(1, 3):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 2, manifest)
        _add_title(page, 80, 90, f"5 金相组织图（第 {pno} 页）", 1, manifest, pno)
        _add_image_block(page, (90, 130, 420, 330), manifest, pno, caption=f"图 {pno} 显微组织 500x")
    _save(doc, "synth_image_caption.pdf", manifest)


# ---------- 7 复杂页眉页脚 ----------
def gen_header_complex():
    doc = _new_doc()
    manifest = {"kind": "header", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest, complex_mode=True, footer="第 X 页 共 Y 页")
        _add_paragraph(
            page,
            (90, 150, 520, 520),
            (
                f"复杂页眉页脚样本第 {pno} 页第一段正文，用于验证双行页眉与页码擦除效果。"
                "本段包含足够多的文字以支撑版面检测，包括标准编号、适用范围、术语定义与判定规则。"
                "检验工作应在受控环境下进行，试验设备应定期校准并保存校准记录，原始数据不得涂改。"
            ),
            manifest,
            pno,
        )
        _add_paragraph(
            page,
            (90, 300, 520, 520),
            (
                f"第 {pno} 页第二段正文：检验方法、抽样数量与复验流程的说明，保证页面内容充实且版面结构清晰。"
                "抽样应按批次随机抽取，抽样数量不少于规定下限，复验结果以二次试验均值作为最终判定依据。"
            ),
            manifest,
            pno,
        )
        _add_paragraph(
            page,
            (90, 450, 520, 620),
            f"第 {pno} 页第三段：记录表格填写要求与结果复核流程，确保每一步操作可追溯。",
            manifest,
            pno,
        )
    _save(doc, "synth_header_complex.pdf", manifest)


# ---------- 8 封面+正文 ----------
def gen_cover_body():
    doc = _new_doc()
    manifest = {"kind": "cover", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 4}
    for pno in range(1, 5):
        page = doc.new_page(width=A4_W, height=A4_H)
        if pno == 1:
            page.insert_text((180, 300), "技术协议封面", fontsize=22, fontname=CJK)
            page.insert_text((170, 340), "文件编号：HS-2026-001", fontsize=11, fontname=CJK)
            manifest["layout_blocks"].append({"page": 1, "type": "title", "bbox": _box(150, 260, 450, 350)})
            manifest["titles"].append({"text": "技术协议封面", "page": 1, "level": 1, "bbox": _box(150, 260, 450, 350)})
        else:
            _header_footer(page, pno, 4, manifest)
            _add_title(page, 80, 90, f"第 {pno - 1} 章 正文", 1, manifest, pno)
            _add_paragraph(
                page,
                (90, 150, 520, 420),
                (
                    f"封面后的正文内容第 {pno - 1} 章，本章介绍检验流程、抽样方法与判定准则。"
                    "内容包含多个段落与完整句式，确保版面检测能够稳定识别文本区域。"
                ),
                manifest,
                pno,
            )
            _add_paragraph(
                page,
                (90, 240, 520, 420),
                f"第 {pno - 1} 章第二节：记录表格填写要求与结果复核流程。",
                manifest,
                pno,
            )
    _save(doc, "synth_cover_body.pdf", manifest)


# ---------- 9 扫描样式 ----------
def gen_scanned_style():
    doc = _new_doc()
    manifest = {"kind": "scanned", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 2}
    for pno in range(1, 3):
        page = doc.new_page(width=A4_W, height=A4_H)
        _add_image_block(page, (0, 0, A4_W, A4_H), manifest, pno, color=(245, 245, 235))
    # 扫描件为整页图片，不参与版面块门禁（评测报告单列说明）
    manifest["layout_blocks"] = []
    _save(doc, "synth_scanned_style.pdf", manifest)


# ---------- 10 脚注 ----------
def gen_footnote():
    doc = _new_doc()
    manifest = {"kind": "text", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 2}
    for pno in range(1, 3):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 2, manifest)
        _add_title(page, 80, 90, f"6 脚注样例（第 {pno} 页）", 1, manifest, pno)
        _add_paragraph(
                page,
                (90, 130, 520, 260),
                "正文内容含脚注引用，脚注用于补充说明术语或数据来源。",
                manifest,
                pno,
            )
        page.insert_text((90, 300), f"注：脚注说明第 {pno} 页。", fontsize=9, fontname=CJK)
        manifest["layout_blocks"].append({"page": pno, "type": "footnote", "bbox": _box(90, 290, 400, 310)})
    _save(doc, "synth_footnote.pdf", manifest)


# ---------- 11 长文档 ----------
def gen_long_multi():
    doc = _new_doc()
    manifest = {"kind": "text", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 8}
    for pno in range(1, 9):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 8, manifest)
        _add_title(page, 80, 90, f"第 {pno} 章 长文档章节", 1, manifest, pno)
        _add_paragraph(page, (90, 130, 520, 420), f"长文档正文第 {pno} 章内容，用于评测多页任务耗时与稳定性。", manifest, pno)
    _save(doc, "synth_long_multi.pdf", manifest)


# ---------- 12 目录+章节 ----------
def gen_toc_chapters():
    doc = _new_doc()
    manifest = {"kind": "text", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 4}
    for pno in range(1, 5):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 4, manifest)
        if pno == 1:
            _add_title(page, 80, 90, "目录", 1, manifest, pno)
            toc = "1 总则\n2 引用文件\n3 术语\n4 检验方法\n5 判定规则"
            page.insert_textbox(pymupdf.Rect(90, 140, 400, 400), toc, fontsize=11, fontname=CJK)
        else:
            _add_title(page, 80, 90, f"{pno - 1} 章节内容", 1, manifest, pno)
            _add_paragraph(page, (90, 130, 520, 300), f"第 {pno - 1} 章正文。", manifest, pno)
    _save(doc, "synth_toc_chapters.pdf", manifest)


# ---------- 13 混合排版 ----------
def gen_mixed_layout():
    doc = _new_doc()
    manifest = {"kind": "mixed", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 3}
    for pno in range(1, 4):
        page = doc.new_page(width=A4_W, height=A4_H)
        _header_footer(page, pno, 3, manifest)
        page.insert_text((200, 90), f"混合排版标题 {chr(64 + pno)}", fontsize=20, fontname=CJK)
        manifest["layout_blocks"].append({"page": pno, "type": "title", "bbox": _box(170, 60, 430, 100)})
        manifest["titles"].append({"text": f"混合排版标题 {chr(64 + pno)}", "page": pno, "level": 1, "bbox": _box(170, 60, 430, 100)})
        _add_paragraph(
                page,
                (90, 130, 520, 260),
                "混合排版正文段落，包含标题、正文、图片与表格多种块。该段落用于验证版面检测对复合布局的识别能力。",
                manifest,
                pno,
            )
        _add_image_block(page, (90, 240, 300, 400), manifest, pno, caption=f"图 {pno} 混合样本")
        _add_table(page, 330, 240, 5, 3, 190, 20, manifest, pno)
    _save(doc, "synth_mixed_layout.pdf", manifest)


# ---------- 14 空白页混合 ----------
def gen_blank_mix():
    doc = _new_doc()
    manifest = {"kind": "mixed", "layout_blocks": [], "titles": [], "tables": [], "texts": [], "header_footers": [], "_pages": 2}
    for pno in range(1, 3):
        page = doc.new_page(width=A4_W, height=A4_H)
        if pno == 1:
            _add_title(page, 80, 90, "7 空白页样本", 1, manifest, pno)
            _add_paragraph(page, (90, 130, 520, 200), "本页为正常内容页。", manifest, pno)
        else:
            page.insert_text((80, 60), "（本页空白）", fontsize=10, fontname=CJK)
            manifest["layout_blocks"].append({"page": 2, "type": "text", "bbox": _box(80, 50, 200, 70)})
            manifest["texts"].append({"text": "（本页空白）", "page": 2, "bbox": _box(80, 50, 200, 70)})
    _save(doc, "synth_blank_mix.pdf", manifest)


GENERATORS = [
    gen_text_single,
    gen_text_two_column,
    gen_table_crosspage,
    gen_table_mixed,
    gen_formula,
    gen_image_caption,
    gen_header_complex,
    gen_cover_body,
    gen_scanned_style,
    gen_footnote,
    gen_long_multi,
    gen_toc_chapters,
    gen_mixed_layout,
    gen_blank_mix,
]


def generate_all(count: int | None = None) -> list[Path]:
    GT_DIR.mkdir(parents=True, exist_ok=True)
    for gen in (GENERATORS[:count] if count else GENERATORS):
        gen()
    out_dir = Path(__file__).resolve().parents[2] / "test_doc" / "generated"
    return sorted(out_dir.glob("*.pdf"))


if __name__ == "__main__":
    paths = generate_all()
    print(f"generated {len(paths)} samples")
    for p in paths:
        print(" -", p.name)
