"""S7 演示：牌号脚注清理（S4 产物）→ 验证 → 评测准备。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.analyze.grade_cleanup import cleanup_record_grades  # noqa: E402
from app_v3.verify.pipeline import verify_records  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    total = {"records": 0, "cleaned": 0, "verify_status": {}, "queue": 0}
    docs = []
    for doc_dir in sorted(BASE.iterdir()):
        if not doc_dir.is_dir():
            continue
        src = doc_dir / "extract" / "s4" / "repaired.json"
        ocr_path = doc_dir / "ocr" / "ocr.json"
        if not src.exists():
            continue
        records = json.loads(src.read_text(encoding="utf-8")).get("records") or []
        cleaned, clean_stats = cleanup_record_grades(records)
        ocr = json.loads(ocr_path.read_text(encoding="utf-8")) if ocr_path.exists() else None
        verified = verify_records(cleaned, ocr)
        outdir = doc_dir / "extract" / "s7"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "repaired.json").write_text(json.dumps({"records": verified["records"]}, ensure_ascii=False), encoding="utf-8")
        (outdir / "verification.json").write_text(json.dumps(verified, ensure_ascii=False, indent=1), encoding="utf-8")
        docs.append({"doc": doc_dir.name, "cleanup": clean_stats, "verify": verified["summary"]})
        total["records"] += clean_stats["total"]
        total["cleaned"] += clean_stats["cleaned"]
        for key, value in verified["summary"]["status"].items():
            total["verify_status"][key] = total["verify_status"].get(key, 0) + value
        total["queue"] += verified["summary"]["queue"]
    report = {"total": total, "documents": docs}
    (EVAL / "s7-grade-cleanup-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s7] records={total['records']} cleaned={total['cleaned']} "
          f"verify_status={total['verify_status']} queue={total['queue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
