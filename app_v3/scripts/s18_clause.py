"""S18 条款通道试点：对少量高缺口文档运行 LLM 条款抽取并评测。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.clause_channel import extract_document  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
OUT = ROOT / ".tmp" / "s18_clause"
EVAL = ROOT / "app_v3" / "eval"
DOCS = ["gbt-3620-1-2016", "astm-b348-25", "gbt-14976-2025", "asme-sb338-2025", "gbt-3077-2015"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default=",".join(DOCS))
    parser.add_argument("--max-chunks", type=int, default=12)
    parser.add_argument("--pages-per-chunk", type=int, default=4)
    args = parser.parse_args()
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in docs:
        ocr_path = BASE / doc / "ocr" / "ocr.json"
        if not ocr_path.exists():
            report.append({"doc": doc, "error": "missing_ocr"})
            continue
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        records = extract_document(ocr, pages_per_chunk=args.pages_per_chunk, max_chunks=args.max_chunks)
        (OUT / f"{doc}.json").write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
        report.append({"doc": doc, "records": len(records)})
        print(f"[s18] {doc}: clause_records={len(records)}", flush=True)
    (EVAL / "s18-clause-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
