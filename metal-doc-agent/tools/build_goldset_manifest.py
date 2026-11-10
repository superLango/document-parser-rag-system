"""Build goldset/v0/manifest.json from the curated selection.

The selection is curated by a human: 20 documents, split into mini / dev /
heldout, with source type measured from the PDF text layer when pypdf is
available. Page/table/profile counts are computed from the OCR markdown.

Usage:
    python tools/build_goldset_manifest.py --corpus "..\\标准文件" --out goldset/v0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.goldset import GoldDocEntry, GoldManifest, goldset_summary
from metal_doc_agent.ingest import ingest
from metal_doc_agent.tablegrid.parser import extract_tables

logging.getLogger("pypdf").setLevel(logging.ERROR)

SELECTION = [
    {
        "doc_id": "qdu302_2015",
        "standard_no": "Q/Du 302-2015",
        "title": "舱段用铝合金锥/筒形轧制锻件技术条件",
        "doc_type": "enterprise",
        "material": "2A14铝合金",
        "product_form": "锥/筒形轧制锻件",
        "md_path": "Q-Du 302-2015.md",
        "pdf_path": "Q-Du 302-2015.pdf",
        "split": "mini",
        "priority": 1,
        "annotation_file": "docs/qdu302_2015.json",
    },
    {
        "doc_id": "gbt40303_2021",
        "standard_no": "GB/T 40303-2021",
        "title": "GH4169合金棒材通用技术条件",
        "doc_type": "gb_t",
        "material": "GH4169镍基高温合金",
        "product_form": "棒材",
        "md_path": "GBT 40303-2021\\GBT 40303-2021   GH4169合金棒材通用技术条件.md",
        "pdf_path": "GBT 40303-2021\\GBT 40303-2021   GH4169合金棒材通用技术条件.pdf",
        "split": "mini",
        "priority": 1,
        "annotation_file": "docs/gbt40303_2021.json",
    },
    {
        "doc_id": "gjb2057a_2018",
        "standard_no": "GJB 2057A-2018",
        "title": "航天用2219铝合金锻件规范",
        "doc_type": "gjb",
        "material": "2219铝合金",
        "product_form": "锻件/锻环",
        "md_path": "GJB2057A-2018\\89.GJB2057A-2018 航天用2219铝合金锻件规范.md",
        "pdf_path": "GJB2057A-2018\\89.GJB2057A-2018 航天用2219铝合金锻件规范.pdf",
        "split": "mini",
        "priority": 1,
        "annotation_file": "docs/gjb2057a_2018.json",
    },
    {
        "doc_id": "gbt1591_2018",
        "standard_no": "GB/T 1591-2018",
        "title": "低合金高强度结构钢",
        "doc_type": "gb_t",
        "material": "低合金高强度钢",
        "product_form": "型钢/板带",
        "md_path": "GBT 1591-2018\\GBT 1591-2018 低合金高强度结构钢.md",
        "pdf_path": "GBT 1591-2018\\GBT 1591-2018 低合金高强度结构钢.pdf",
        "split": "dev",
        "priority": 1,
        "notes": "M1.5 引用/复杂表头基准；OCR 表头存在粘连。",
    },
    {
        "doc_id": "gbt14992_2015",
        "standard_no": "GB/T 14992-2015",
        "title": "高温合金和金属间化合物高温材料的分类和牌号",
        "doc_type": "classification",
        "material": "高温合金",
        "product_form": "牌号分类",
        "md_path": "GBT 14992-2015\\GBT 14992-2015 高温合金和金属间化合物高温材料的分类和牌号.md",
        "pdf_path": "GBT 14992-2015\\GBT 14992-2015 高温合金和金属间化合物高温材料的分类和牌号.pdf",
        "split": "dev",
        "priority": 1,
        "notes": "PDF 文本层仅 13 字符/页，OCR 版式偏差需关注。",
    },
    {
        "doc_id": "gbt3191_1998",
        "standard_no": "GB/T 3191-1998",
        "title": "铝及铝合金挤压棒材",
        "doc_type": "gb_t",
        "material": "铝合金",
        "product_form": "挤压棒材",
        "md_path": "GBT 3191-1998\\GBT 3191-1998 铝及铝合金挤压棒材.md",
        "pdf_path": "GBT 3191-1998\\GBT 3191-1998 铝及铝合金挤压棒材.pdf",
        "split": "dev",
        "priority": 2,
        "notes": "旧版本，用于版本差异对照。",
    },
    {
        "doc_id": "gbt3191_2010",
        "standard_no": "GB/T 3191-2010",
        "title": "铝及铝合金挤压棒材",
        "doc_type": "gb_t",
        "material": "铝合金",
        "product_form": "挤压棒材",
        "md_path": "GB∕T 3191-2010\\GB∕T 3191-2010 铝及铝合金挤压棒材.md",
        "pdf_path": "GB∕T 3191-2010\\GB∕T 3191-2010 铝及铝合金挤压棒材.pdf",
        "split": "dev",
        "priority": 2,
        "notes": "与 1998 版成对，用于版本引用/差异。",
    },
    {
        "doc_id": "gbt1220_2007",
        "standard_no": "GB/T 1220-2007",
        "title": "不锈钢棒",
        "doc_type": "gb_t",
        "material": "不锈钢",
        "product_form": "棒材",
        "md_path": "GB-T1220-2007\\GB-T1220-2007 不锈钢棒.md",
        "pdf_path": "GB-T1220-2007\\GB-T1220-2007 不锈钢棒.pdf",
        "split": "dev",
        "priority": 1,
    },
    {
        "doc_id": "gbt33084_2016",
        "standard_no": "GB/T 33084-2016",
        "title": "大型合金结构钢锻件 技术条件",
        "doc_type": "gb_t",
        "material": "合金结构钢",
        "product_form": "大型锻件",
        "md_path": "GBT33084-2016\\GBT33084-2016.md",
        "pdf_path": "GBT33084-2016\\GBT33084-2016.pdf",
        "split": "dev",
        "priority": 1,
    },
    {
        "doc_id": "gbt3203_2016",
        "standard_no": "GB/T 3203-2016",
        "title": "渗碳轴承钢",
        "doc_type": "gb_t",
        "material": "渗碳轴承钢",
        "product_form": "棒材/钢材",
        "md_path": "GBT3203-2016\\GBT3203-2016.md",
        "pdf_path": "GBT3203-2016\\GBT3203-2016.pdf",
        "split": "dev",
        "priority": 2,
    },
    {
        "doc_id": "gbt3880_1_2012",
        "standard_no": "GB/T 3880.1-2012",
        "title": "一般工业用铝及铝合金板、带材 第1部分：一般要求",
        "doc_type": "gb_t",
        "material": "铝合金",
        "product_form": "板/带材",
        "md_path": "GBT3880.1-2012\\B360  GBT3880.1-2012一般工业用铝及铝合金板、带材第1部分：一般要求.md",
        "pdf_path": "GBT3880.1-2012\\B360  GBT3880.1-2012一般工业用铝及铝合金板、带材第1部分：一般要求.pdf",
        "split": "dev",
        "priority": 2,
    },
    {
        "doc_id": "gbt4437_1_2015",
        "standard_no": "GB/T 4437.1-2015",
        "title": "铝及铝合金热挤压管 第1部分：无缝圆管",
        "doc_type": "gb_t",
        "material": "铝合金",
        "product_form": "无缝圆管",
        "md_path": "GBT 4437.1-2015\\GBT 4437.1-2015 铝及铝合金热挤压管 第1部分：无缝圆管.md",
        "pdf_path": "GBT 4437.1-2015\\GBT 4437.1-2015 铝及铝合金热挤压管 第1部分：无缝圆管.pdf",
        "split": "dev",
        "priority": 2,
        "notes": "混合文本层（75 字符/页），按扫描件路径处理。",
    },
    {
        "doc_id": "gbt6892_2015",
        "standard_no": "GB/T 6892-2015",
        "title": "一般工业用铝及铝合金挤压型材",
        "doc_type": "gb_t",
        "material": "铝合金",
        "product_form": "挤压型材",
        "md_path": "GBT 6892-2015\\GBT 6892-2015.md",
        "pdf_path": "GBT 6892-2015\\GBT 6892-2015 一般工业用铝及铝合金挤压型材.pdf",
        "split": "dev",
        "priority": 2,
    },
    {
        "doc_id": "gjb2294a_2014",
        "standard_no": "GJB 2294A-2014",
        "title": "航空用不锈钢及耐热钢棒规范",
        "doc_type": "gjb",
        "material": "不锈钢/耐热钢",
        "product_form": "棒材",
        "md_path": "GJB 2294A-2014\\GJB 2294A-2014.md",
        "pdf_path": "GJB 2294A-2014\\GJB 2294A-2014.pdf",
        "split": "dev",
        "priority": 1,
    },
    {
        "doc_id": "gjb5301_2004",
        "standard_no": "GJB 5301-2004",
        "title": "航空用高温合金环形件规范",
        "doc_type": "gjb",
        "material": "高温合金",
        "product_form": "环形件",
        "md_path": "25.GJB 5301-2004 航空用高温合金环形件规范.md",
        "pdf_path": "25.GJB 5301-2004 航空用高温合金环形件规范.pdf",
        "split": "dev",
        "priority": 1,
    },
    {
        "doc_id": "gjb3325a_2019",
        "standard_no": "GJB 3325A-2019",
        "title": "航天固体火箭发动机用超高强度钢锻件规范",
        "doc_type": "gjb",
        "material": "超高强度钢",
        "product_form": "锻件",
        "md_path": "GJB3325A-2019\\GJB3325A-2019.md",
        "pdf_path": "GJB3325A-2019\\GJB3325A-2019.pdf",
        "split": "heldout",
        "priority": 2,
    },
    {
        "doc_id": "jx25_035",
        "standard_no": "JX-25-035",
        "title": "GH4698高温合金棒材采购技术协议",
        "doc_type": "agreement",
        "material": "GH4698高温合金",
        "product_form": "棒材",
        "md_path": "JX-25-035\\JX-25-035+GH4698高温合金棒材采购技术协议.md",
        "pdf_path": "JX-25-035\\JX-25-035+GH4698高温合金棒材采购技术协议.pdf",
        "split": "heldout",
        "priority": 1,
        "notes": "化学表转置，T3 复杂表型候选。",
    },
    {
        "doc_id": "mas7079_b",
        "standard_no": "MAS 7079",
        "title": "叶片用GH4720Li合金锻件",
        "doc_type": "enterprise",
        "material": "GH4720Li高温合金",
        "product_form": "叶片锻件",
        "md_path": "MAS7079   B版   叶片用GH4720Li合金锻件.md",
        "pdf_path": "MAS7079   B版   叶片用GH4720Li合金锻件.pdf",
        "split": "heldout",
        "priority": 2,
    },
    {
        "doc_id": "qs10_0351_2004",
        "standard_no": "Q/S10-0351-2004",
        "title": "TA15钛合金锻制棒材",
        "doc_type": "enterprise",
        "material": "TA15钛合金",
        "product_form": "锻制棒材",
        "md_path": "7、Q／S10-0351-2004   TA15钛合金锻制棒材.md",
        "pdf_path": "7、Q／S10-0351-2004   TA15钛合金锻制棒材.pdf",
        "split": "heldout",
        "priority": 2,
    },
    {
        "doc_id": "sjx100_410_2019",
        "standard_no": "100.410SJX-D-2019-027",
        "title": "1Cr12Ni3MoVN钢前机匣上下半部锻件",
        "doc_type": "enterprise",
        "material": "1Cr12Ni3MoVN钢",
        "product_form": "机匣锻件",
        "md_path": "100.410SJX-D-2019-027  1Cr12Ni3MoVN钢前机匣上下半部锻件.md",
        "pdf_path": "100.410SJX-D-2019-027  1Cr12Ni3MoVN钢前机匣上下半部锻件.pdf",
        "split": "heldout",
        "priority": 2,
    },
]

REQUIREMENTS = {
    "documents": 20,
    "digital_native": 8,
    "scanned": 12,
    "doc_types": 4,
    "table_profiles": 3,
    "annotated": 3,
}


def detect_source_type(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "unknown"
    try:
        reader = PdfReader(str(pdf_path))
        counts = []
        for page in reader.pages:
            try:
                counts.append(len((page.extract_text() or "").strip()))
            except Exception:
                counts.append(0)
        if not counts:
            return "unknown"
        nonempty = sum(1 for count in counts if count > 0)
        per_page = sum(counts) / len(counts)
        if nonempty / len(counts) >= 0.8 and per_page >= 200:
            return "digital_native"
        if per_page < 30:
            return "scanned"
        return "hybrid"
    except Exception:
        return "unknown"


def build(corpus: Path, out_dir: Path) -> GoldManifest:
    entries: list[GoldDocEntry] = []
    for item in SELECTION:
        md_path = corpus / item["md_path"]
        pdf_path = corpus / item["pdf_path"]
        if not md_path.exists():
            raise FileNotFoundError(f"{item['doc_id']}: md not found: {md_path}")
        if not pdf_path.exists():
            raise FileNotFoundError(f"{item['doc_id']}: pdf not found: {pdf_path}")
        _, pages = ingest(md_path)
        tables = extract_tables(pages)
        profiles = sorted({table.profile for table in tables})
        entry = GoldDocEntry(
            **item,
            source_type=detect_source_type(pdf_path),
            pages=len(pages),
            tables=len(tables),
            profiles=profiles,
            annotation_status=(
                "annotated" if item.get("annotation_file") else "selected"
            ),
        )
        entries.append(entry)

    manifest = GoldManifest(
        goldset_version="v0",
        created_at=date.today().isoformat(),
        corpus_root="../../../标准文件",
        requirements=REQUIREMENTS,
        documents=entries,
        notes=[
            "当前语料仅有 6 份数字原生 PDF（另 1 份混合），未达到计划 8 份；"
            "需补充原生 PDF，或由业务接受该缺口。",
            "标注 3 份迷你黄金集为 draft，需领域专家双人复核后转 reviewed/verified。",
        ],
    )
    manifest.summary = goldset_summary(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=r"..\标准文件")
    parser.add_argument("--out", default="goldset/v0")
    args = parser.parse_args()

    corpus = (ROOT / args.corpus).resolve() if not Path(args.corpus).is_absolute() else Path(args.corpus)
    out_dir = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build(corpus, out_dir)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_dir / 'manifest.json'}")
    print(json.dumps(manifest.summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
