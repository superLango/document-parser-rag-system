"""生成 app_v3 基准数据 manifest（26 份文档 + 对照 JSON + 历史基线指标）。

用法（仓库根目录）：
  python app_v3/benchmark/build_manifest.py
可选参数：
  --batch20-metrics .tmp/batch20/metrics.json
  --six-report     .tmp/v2six/six-report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
DOCS = BENCH / "docs"
GOLD = BENCH / "gold"

DOCS_20 = [
    "asme-sb338-2025", "ams-4928x", "iso-5832-3-2021", "hb-20079-2012",
    "gjb-9581-2018", "gjb-2351a-2021", "gjb-2296a-2005", "gjb-1951a-2020",
    "gbt-14976-2025", "gbt-8547-2019", "gbt-5231-2022", "gbt-3623-2022",
    "gbt-3620-1-2016", "gbt-3077-2015", "gbt-2965-2023", "gbt-2054-2023",
    "astm-b348-25", "nbt-47019-8-2011", "xx454-2022", "yst-656-2015",
]
OLD_6 = [
    ("gbt-713.7-2023", "doc1"),
    ("gbt-1591-2018", "doc2"),
    ("gbt-3191-1998", "docA"),
    ("gbt-6892-2015", "docB"),
    ("gjb-2294-1995", "docC"),
    ("yst-397-2015", "docD"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch20-metrics", default=str(ROOT / ".tmp/batch20/metrics.json"))
    parser.add_argument("--six-report", default=str(ROOT / ".tmp/v2six/six-report.json"))
    args = parser.parse_args()
    metrics = load_json(Path(args.batch20_metrics))
    six = load_json(Path(args.six_report))
    by_slug = {row["slug"]: row for row in metrics.get("docs") or [] if row.get("slug")}
    six_by_doc = {row.get("tag"): row for row in six.get("docs") or [] if row.get("tag")}

    entries = []
    for slug in DOCS_20:
        pdf = DOCS / f"{slug}.pdf"
        gold = GOLD / f"{slug}.json"
        baseline = by_slug.get(slug) or {}
        entries.append({
            "id": slug,
            "pdf": str(pdf.relative_to(BENCH)),
            "gold": str(gold.relative_to(BENCH)),
            "pdf_sha256": sha256(pdf) if pdf.exists() else "",
            "gold_sha256": sha256(gold) if gold.exists() else "",
            "pdf_bytes": pdf.stat().st_size if pdf.exists() else 0,
            "gold_bytes": gold.stat().st_size if gold.exists() else 0,
            "source": "20-doc-batch",
            "baseline_v2": {
                "matched": baseline.get("matched"),
                "value_exact": baseline.get("value_exact"),
                "consistency": baseline.get("consistency"),
                "coverage": baseline.get("coverage_rate"),
                "seconds": baseline.get("time"),
                "gold_total": baseline.get("gold_total"),
            },
        })
    for slug, tag in OLD_6:
        pdf = DOCS / f"{slug}.pdf"
        gold = GOLD / f"{slug}.json"
        row = six_by_doc.get(tag) or {}
        entries.append({
            "id": slug,
            "pdf": str(pdf.relative_to(BENCH)),
            "gold": str(gold.relative_to(BENCH)),
            "pdf_sha256": sha256(pdf) if pdf.exists() else "",
            "gold_sha256": sha256(gold) if gold.exists() else "",
            "pdf_bytes": pdf.stat().st_size if pdf.exists() else 0,
            "gold_bytes": gold.stat().st_size if gold.exists() else 0,
            "source": "v2-six-replay",
            "baseline_v2": {
                "matched": row.get("matched"),
                "value_exact": row.get("value_exact"),
                "consistency": row.get("consistency"),
                "coverage": row.get("coverage_rate"),
                "seconds": None,
                "gold_total": (row.get("by_category") or {}).values() and sum((row.get("by_category") or {}).values()),
            },
        })
    manifest = {
        "schema_version": "benchmark.v1",
        "created_at": time.strftime("%F %T"),
        "description": "app_v3 基准数据：20 份批量测试 + 6 份早期文档（共 26 份 PDF + 对照 JSON）",
        "notes": [
            "PDF 为本地备份（体积较大，默认不入 git）；gold JSON 与 manifest 入库。",
            "baseline_v2 为冻结版 v2 路线的历史指标，仅作对照，不用于调参。",
            "评测时必须使用固定 gold 与盲测集；不得用 gold 反推规则。",
        ],
        "counts": {"documents": len(entries), "gold": len([entry for entry in entries if entry["gold_sha256"]])},
        "documents": entries,
    }
    out = BENCH / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[benchmark] manifest -> {out} documents={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
