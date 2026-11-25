"""S13 路由试点：在 6 份高潜力冻结文档上，按验证器自评分选择 S9 / 全链路。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.router import choose_channel, filter_recovery_unresolved  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
FULL = ROOT / ".tmp" / "s12_full"
OUT = ROOT / ".tmp" / "s13_router"
EVAL = ROOT / "app_v3" / "eval"
DOCS = [
    "gbt-8547-2019", "hb-20079-2012", "xx454-2022",
    "gbt-2965-2023", "gbt-3620-1-2016", "astm-b348-25",
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in DOCS:
        s9 = BASE / doc / "extract" / "s8" / "repaired.json"
        full = FULL / doc / "assembled" / "assembly-report.json"
        ocr = BASE / doc / "ocr" / "ocr.json"
        if not s9.exists() or not full.exists() or not ocr.exists():
            report.append({"doc": doc, "error": "missing"})
            continue
        s9_records = json.loads(s9.read_text(encoding="utf-8")).get("records") or []
        full_records = json.loads(full.read_text(encoding="utf-8")).get("records") or []
        ocr_data = json.loads(ocr.read_text(encoding="utf-8"))
        routed = choose_channel(s9_records, full_records, ocr_data)
        filtered = filter_recovery_unresolved(routed["records"], ocr_data)
        (OUT / f"{doc}.json").write_text(json.dumps({"records": routed["records"]}, ensure_ascii=False), encoding="utf-8")
        (OUT / f"{doc}-filtered.json").write_text(json.dumps({"records": filtered}, ensure_ascii=False), encoding="utf-8")
        report.append({
            "doc": doc,
            "channel": routed["channel"],
            "s9_score": routed["s9_score"],
            "full_score": routed["full_score"],
            "records": len(routed["records"]),
            "filtered_records": len(filtered),
        })
        print(f"[s13] {doc}: channel={routed['channel']} s9={routed['s9_score']['score']} "
              f"full={routed['full_score']['score']} records={len(routed['records'])}", flush=True)
    (EVAL / "s13-routing-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
