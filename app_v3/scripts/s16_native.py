"""S16 原生表格通道试点：模型列描述 + 代码展开，先在少量文档验证。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.table_schema_channel import (  # noqa: E402
    describe_tables, extract_tables, select_candidate_tables,
)
from app_v3.table_program.ir import load_tables  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
OUT = ROOT / ".tmp" / "s16_native"
EVAL = ROOT / "app_v3" / "eval"
DOCS = ["gbt-5231-2022", "gbt-3077-2015", "gjb-1951a-2020"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default=",".join(DOCS))
    parser.add_argument("--max-tables", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in docs:
        ocr_path = BASE / doc / "ocr" / "ocr.json"
        s9_path = BASE / doc / "extract" / "s8" / "repaired.json"
        if not ocr_path.exists():
            report.append({"doc": doc, "error": "missing_ocr"})
            continue
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        tables = load_tables(ocr)
        candidates = select_candidate_tables(ocr, max_tables=args.max_tables)
        descriptors = describe_tables(candidates, concurrency=args.concurrency)
        native = extract_tables(candidates, descriptors)
        (OUT / f"{doc}.json").write_text(json.dumps({"records": native}, ensure_ascii=False), encoding="utf-8")
        s9 = json.loads(s9_path.read_text(encoding="utf-8")).get("records") if s9_path.exists() else []
        merged = s9 + native
        (OUT / f"{doc}-merged.json").write_text(json.dumps({"records": merged}, ensure_ascii=False), encoding="utf-8")
        report.append({
            "doc": doc,
            "candidates": [table.table_id for table in candidates],
            "described": len(descriptors),
            "native_records": len(native),
            "merged_records": len(merged),
            "categories": {},
        })
        print(f"[s16] {doc}: tables={len(candidates)} described={len(descriptors)} native={len(native)}", flush=True)
    (EVAL / "s16-native-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
