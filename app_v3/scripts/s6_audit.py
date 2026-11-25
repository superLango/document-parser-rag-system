"""S6 审计：汇总 S5 验证队列，输出原因/类别/文档分布。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.verify.audit import audit_verification_files, render_markdown  # noqa: E402

BASE = ROOT / ".tmp" / "batch20"
EVAL = ROOT / "app_v3" / "eval"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    files = sorted(BASE.glob("*/extract/s5/verification.json"))
    audit = audit_verification_files(files)
    (EVAL / "s6-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "app_v3" / "docs" / "S6-audit.md").write_text(render_markdown(audit), encoding="utf-8")
    print(f"[s6-audit] docs={audit['documents']} queue={audit['queue_total']} "
          f"reasons={audit['by_reason']}")
    print(f"[s6-audit] top_docs={audit['top_documents']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
