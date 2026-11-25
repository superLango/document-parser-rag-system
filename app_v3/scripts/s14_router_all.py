"""S14：将 S13 路由应用到 20 份冻结文档（有全链路结果的走路由，否则保留 S9）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.router import choose_channel  # noqa: E402
from app_v3.eval.run_eval import DEFAULT_DOCS  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
FULL = ROOT / ".tmp" / "s12_full"
OUT = ROOT / ".tmp" / "s14_routed"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in DEFAULT_DOCS:
        s9 = BASE / doc / "extract" / "s8" / "repaired.json"
        full = FULL / doc / "assembled" / "assembly-report.json"
        ocr = BASE / doc / "ocr" / "ocr.json"
        if not s9.exists() or not ocr.exists():
            report.append({"doc": doc, "error": "missing_s9_or_ocr"})
            continue
        s9_records = json.loads(s9.read_text(encoding="utf-8")).get("records") or []
        ocr_data = json.loads(ocr.read_text(encoding="utf-8"))
        if full.exists():
            full_records = json.loads(full.read_text(encoding="utf-8")).get("records") or []
            routed = choose_channel(s9_records, full_records, ocr_data)
            channel = routed["channel"]
            records = routed["records"]
            entry = {
                "doc": doc, "channel": channel,
                "coverage_gain": routed["coverage_gain"],
                "s9_keys": routed["s9_keys"], "full_keys": routed["full_keys"],
                "s9_records": len(s9_records), "full_records": len(full_records),
            }
        else:
            channel = "s9_no_full"
            records = s9_records
            entry = {"doc": doc, "channel": channel, "s9_records": len(s9_records)}
        (OUT / f"{doc}.json").write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
        report.append(entry)
        print(f"[s14] {doc}: {channel} records={len(records)}", flush=True)
    (EVAL / "s14-routing-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    full_docs = sum(1 for item in report if item.get("channel") in {"full_rebind", "s9"})
    print(f"[s14] routed_docs={len(report)} with_full={full_docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
