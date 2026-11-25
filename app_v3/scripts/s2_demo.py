"""S2 演示：对 20 份 v2 产物执行 牌号修复 + 验证，输出结果并准备评测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.analyze.repair import repair_records  # noqa: E402
from app_v3.verify.pipeline import verify_records  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    docs_report = []
    total = {"records": 0, "repaired_from_table": 0, "repaired_from_document": 0,
             "unresolved_repair": 0, "verify_status": {}, "verify_diagnostics": {}, "queue": 0}
    for doc_dir in sorted(BASE.iterdir()):
        if not doc_dir.is_dir():
            continue
        pred = doc_dir / "extract" / "assembled" / "assembly-report.json"
        ocr_path = doc_dir / "ocr" / "ocr.json"
        if not pred.exists() or not ocr_path.exists():
            continue
        payload = json.loads(pred.read_text(encoding="utf-8"))
        records = payload.get("records") or []
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        pages = [str(page.get("markdown") or "") for page in ocr.get("pages") or []]
        repaired, repair_stats = repair_records(records, ocr=ocr, pages_markdown=pages)
        verified = verify_records(repaired, ocr)
        outdir = doc_dir / "extract" / "s2"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "repaired.json").write_text(json.dumps({"records": repaired}, ensure_ascii=False), encoding="utf-8")
        (outdir / "verification.json").write_text(json.dumps(verified, ensure_ascii=False, indent=1), encoding="utf-8")
        docs_report.append({"doc": doc_dir.name, "repair": repair_stats, "verify": verified["summary"]})
        total["records"] += repair_stats["total"]
        total["repaired_from_table"] += repair_stats["repaired_from_table"]
        total["repaired_from_document"] += repair_stats["repaired_from_document"]
        total["unresolved_repair"] += repair_stats["unresolved"]
        for key, value in verified["summary"]["status"].items():
            total["verify_status"][key] = total["verify_status"].get(key, 0) + value
        for key, value in verified["summary"]["diagnostics"].items():
            total["verify_diagnostics"][key] = total["verify_diagnostics"].get(key, 0) + value
        total["queue"] += verified["summary"]["queue"]
    report = {"total": total, "documents": docs_report}
    (EVAL / "s2-repair-verify-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s2] records={total['records']} repaired_table={total['repaired_from_table']} "
          f"repaired_doc={total['repaired_from_document']} repair_unresolved={total['unresolved_repair']} "
          f"verify_status={total['verify_status']} queue={total['queue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
