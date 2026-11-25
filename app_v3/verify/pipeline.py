"""验证器流水线：证据 + 值守恒 + 条件 + 冲突 → 验证结果/未解决队列。"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .conditions import validate_conditions
from .conflicts import detect_conflicts
from .conservation import validate_conservation
from .evidence import validate_evidence
from .queue import build_queue


def verify_records(records: list[dict[str, Any]], ocr: dict[str, Any] | None = None) -> dict[str, Any]:
    tables = {str(table.get("table_id")): table for table in (ocr or {}).get("tables") or []}
    page_count = len((ocr or {}).get("pages") or []) or None
    conflict_diags, conflicts = detect_conflicts(records)
    verified_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        diagnostics: list[dict[str, Any]] = []
        diagnostics.extend(validate_evidence(record, tables, page_count))
        diagnostics.extend(validate_conservation(record, tables))
        diagnostics.extend(validate_conditions(record))
        diagnostics.extend(conflict_diags.get(index) or [])
        status = "ok"
        if any(diagnostic.get("severity") == "error" for diagnostic in diagnostics):
            status = "unresolved"
        elif diagnostics:
            status = "warn"
        output = dict(record)
        output["verification"] = {"status": status, "diagnostics": diagnostics}
        verified_records.append(output)
    queue = build_queue(verified_records)
    summary = {
        "total": len(verified_records),
        "status": dict(Counter(record["verification"]["status"] for record in verified_records)),
        "diagnostics": dict(Counter(diagnostic.get("code") for record in verified_records
                                    for diagnostic in record["verification"]["diagnostics"])),
        "queue": len(queue),
        "conflicts": len(conflicts),
        "tables": len(tables),
    }
    return {
        "schema_version": "verification.v1",
        "summary": summary,
        "records": verified_records,
        "queue": queue,
        "conflicts": conflicts[:50],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="app_v3 S2 验证器")
    parser.add_argument("--input", required=True)
    parser.add_argument("--ocr", default="")
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--queue-out", default="")
    parser.add_argument("--records-out", default="")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    ocr = json.loads(Path(args.ocr).read_text(encoding="utf-8")) if args.ocr and Path(args.ocr).exists() else None
    result = verify_records(records or [], ocr)
    Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.queue_out:
        Path(args.queue_out).write_text(json.dumps(result["queue"], ensure_ascii=False, indent=1), encoding="utf-8")
    if args.records_out:
        Path(args.records_out).write_text(json.dumps({"records": result["records"]}, ensure_ascii=False), encoding="utf-8")
    print(f"[verify] total={result['summary']['total']} status={result['summary']['status']} "
          f"queue={result['summary']['queue']} conflicts={result['summary']['conflicts']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
