"""S4 演示：牌号体系修复（表格 Grade/UNS）+ 条件补全 + 验证。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.analyze.condition_repair import repair_conditions  # noqa: E402
from app_v3.analyze.repair import repair_records  # noqa: E402
from app_v3.verify.pipeline import verify_records  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    docs_report = []
    total = {"records": 0, "grade_table": 0, "grade_document": 0, "condition_repaired": 0,
             "verify_status": {}, "verify_diagnostics": {}, "queue": 0}
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
        grade_repaired, grade_stats = repair_records(
            records, ocr=ocr, pages_markdown=pages, table_repair=True, document_repair=True
        )
        condition_repaired, condition_stats = repair_conditions(grade_repaired, ocr)
        verified = verify_records(condition_repaired, ocr)
        outdir = doc_dir / "extract" / "s4"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "repaired.json").write_text(json.dumps({"records": verified["records"]}, ensure_ascii=False), encoding="utf-8")
        (outdir / "verification.json").write_text(json.dumps(verified, ensure_ascii=False, indent=1), encoding="utf-8")
        docs_report.append({"doc": doc_dir.name, "grade": grade_stats, "conditions": condition_stats,
                            "verify": verified["summary"]})
        total["records"] += grade_stats["total"]
        total["grade_table"] += grade_stats["repaired_from_table"]
        total["grade_document"] += grade_stats["repaired_from_document"]
        total["condition_repaired"] += condition_stats["normalized"]
        for key, value in verified["summary"]["status"].items():
            total["verify_status"][key] = total["verify_status"].get(key, 0) + value
        for key, value in verified["summary"]["diagnostics"].items():
            total["verify_diagnostics"][key] = total["verify_diagnostics"].get(key, 0) + value
        total["queue"] += verified["summary"]["queue"]
    report = {"total": total, "documents": docs_report}
    (EVAL / "s4-repair-verify-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s4] records={total['records']} grade_table={total['grade_table']} "
          f"grade_document={total['grade_document']} condition_repaired={total['condition_repaired']} "
          f"verify_status={total['verify_status']} queue={total['queue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
