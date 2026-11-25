"""S17：原生记录质量过滤后合并到 20 份冻结文档并评测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.record_filter import merge_quality  # noqa: E402
from app_v3.eval.run_eval import DEFAULT_DOCS  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
NATIVE = ROOT / ".tmp" / "s16_native"
OUT = ROOT / ".tmp" / "s17_quality"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in DEFAULT_DOCS:
        base_path = BASE / doc / "extract" / "s8" / "repaired.json"
        if not base_path.exists():
            report.append({"doc": doc, "error": "missing_base"})
            continue
        base = json.loads(base_path.read_text(encoding="utf-8")).get("records") or []
        native_path = NATIVE / f"{doc}.json"
        native = json.loads(native_path.read_text(encoding="utf-8")).get("records") or [] if native_path.exists() else []
        merged, stats = merge_quality(base, native)
        (OUT / f"{doc}.json").write_text(json.dumps({"records": merged}, ensure_ascii=False), encoding="utf-8")
        report.append({"doc": doc, "stats": stats, "merged": len(merged)})
        print(f"[s17] {doc}: base={len(base)} native={len(native)} kept={stats['kept']} merged={len(merged)}", flush=True)
    (EVAL / "s17-quality-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s17] docs={len(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
