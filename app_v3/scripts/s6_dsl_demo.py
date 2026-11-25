"""S6 DSL 演示：在真实 OCR 表（gbt-2054 T9）上执行 melt 程序并回放校验。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.table_program.engine import execute_program  # noqa: E402
from app_v3.table_program.ir import load_tables  # noqa: E402
from app_v3.table_program.replay import validate_program  # noqa: E402

EVAL = ROOT / "app_v3" / "eval"
OCR = ROOT / ".tmp" / "batch20" / "gbt-2054-2023" / "ocr" / "ocr.json"


def main() -> int:
    EVAL.mkdir(parents=True, exist_ok=True)
    ocr = json.loads(OCR.read_text(encoding="utf-8"))
    tables = load_tables(ocr)
    table = next((ir for ir in tables.values() if ir.table_id == "T9"), None)
    if table is None:
        print("[s6-dsl] T9 not found")
        return 1
    program = {
        "schema_version": "table_program.v1",
        "table_id": table.table_id,
        "header_rows": table.header_rows,
        "steps": [
            {"op": "explode", "column": 0},
            {"op": "melt", "id_columns": [0, 1, 2],
             "value_columns": [
                 {"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa", "category": "室温拉伸",
                  "conditions": {"试验温度": "室温"}},
                 {"column": 4, "measure": "规定塑性延伸强度(Rp0.2)", "unit": "MPa", "category": "室温拉伸",
                  "conditions": {"试验温度": "室温"}},
                 {"column": 5, "measure": "断后伸长率(A)", "unit": "%", "category": "室温拉伸",
                  "conditions": {"试验温度": "室温"}},
                 {"column": 6, "measure": "维氏硬度(HV)", "unit": "HV", "category": "硬度试验"},
                 {"column": 7, "measure": "洛氏硬度(HRB)", "unit": "HRB", "category": "硬度试验"},
             ]},
        ],
    }
    records = execute_program(program, table)
    validation = validate_program(program, table, records)
    result = {"table": table.to_dict(), "program": program, "records": len(records),
              "validation": validation, "sample": records[:3]}
    (EVAL / "s6-dsl-demo.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[s6-dsl] table={table.table_id} records={len(records)} "
          f"validation_ok={validation['ok']} coverage={validation['coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
