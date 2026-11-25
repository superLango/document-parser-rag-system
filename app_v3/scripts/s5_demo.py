"""S5 演示：在 S4 修复产物上运行验证器（证据感知冲突分级）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.verify.pipeline import verify_records  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    total = {"records": 0, "verify_status": {}, "verify_diagnostics": {}, "queue": 0}
    docs = []
    for doc_dir in sorted(BASE.iterdir()):
        if not doc_dir.is_dir():
            continue
        src = doc_dir / "extract" / "s4" / "repaired.json"
        ocr_path = doc_dir / "ocr" / "ocr.json"
        if not src.exists() or not ocr_path.exists():
            continue
        records = json.loads(src.read_text(encoding="utf-8")).get("records") or []
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        result = verify_records(records, ocr)
        outdir = doc_dir / "extract" / "s5"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        docs.append({"doc": doc_dir.name, "summary": result["summary"]})
        total["records"] += result["summary"]["total"]
        for key, value in result["summary"]["status"].items():
            total["verify_status"][key] = total["verify_status"].get(key, 0) + value
        for key, value in result["summary"]["diagnostics"].items():
            total["verify_diagnostics"][key] = total["verify_diagnostics"].get(key, 0) + value
        total["queue"] += result["summary"]["queue"]
    report = {"total": total, "documents": docs}
    (EVAL / "s5-verification-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s5] records={total['records']} status={total['verify_status']} queue={total['queue']} "
          f"diagnostics={total['verify_diagnostics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
