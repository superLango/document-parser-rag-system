"""S11 WP1.0 全表重绑定试点：对未绑定的规范量表重新绑定并合并评测。

只处理"未使用但含规范量列"的表；不替换已有记录。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app_v3.channels.table_recover import classify_header, measure_label  # noqa: E402
from app_v3.normalize.grade import parse_grade_cell  # noqa: E402
from app_v3.normalize.items import normalize_item  # noqa: E402
from app_v3.table_program.ir import load_tables  # noqa: E402

PY = str(ROOT / "new_app" / ".venv" / "Scripts" / "python.exe")
DEV = ROOT / "new_app" / "scripts" / "dev"
BASE = ROOT / ".tmp" / "batch20"
OUT = ROOT / ".tmp" / "s11_rebind"
REMOTE = "grainuser@192.168.188.75"


def candidates(ocr: dict, used: set[str]) -> list[str]:
    tables = load_tables(ocr)
    result = []
    for table_id, ir in tables.items():
        if table_id in used:
            continue
        labels = []
        for index in range(ir.width):
            label = measure_label(ir, index)
            if label and classify_header(label):
                labels.append(classify_header(label))
        if labels:
            result.append(table_id)
    return result


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="S11 WP1.0 全表重绑定试点")
    parser.add_argument("--docs", default="", help="逗号分隔的文档名；缺省处理所有有候选的文档")
    args = parser.parse_args()
    selected = {item.strip() for item in args.docs.split(",") if item.strip()}
    OUT.mkdir(parents=True, exist_ok=True)
    docs_report = []
    for doc_dir in sorted(BASE.iterdir()):
        if not doc_dir.is_dir():
            continue
        if selected and doc_dir.name not in selected:
            continue
        ocr_path = doc_dir / "ocr" / "ocr.json"
        s4 = doc_dir / "extract" / "s4" / "repaired.json"
        if not ocr_path.exists() or not s4.exists():
            continue
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
        records = json.loads(s4.read_text(encoding="utf-8")).get("records") or []
        used = {str(record.get("source_table")) for record in records}
        table_ids = candidates(ocr, used)
        if not table_ids:
            docs_report.append({"doc": doc_dir.name, "candidates": 0, "recovered": 0})
            continue
        work = OUT / doc_dir.name
        work.mkdir(parents=True, exist_ok=True)
        if (work / "merged.json").exists():
            existing = json.loads((work / "merged.json").read_text(encoding="utf-8")).get("records") or []
            docs_report.append({"doc": doc_dir.name, "candidates": len(table_ids),
                                "recovered": max(0, len(existing) - len(records)), "resumed": True})
            continue
        bind = work / "bind"
        expanded = work / "expanded"
        code, log = run([
            PY, str(DEV / "dsh_bind_v2.py"), "--ocr", str(ocr_path),
            "--tables", ",".join(table_ids), "--auto", "--outdir", str(bind),
            "--vote", "1", "--concurrency", "6", "--min-cols", "2", "--timeout", "120",
            "--skip-profiles", "", "--remote", REMOTE,
        ], timeout=900)
        (work / "bind.log").write_text(log, encoding="utf-8")
        if code != 0:
            docs_report.append({"doc": doc_dir.name, "candidates": len(table_ids), "error": "bind_failed"})
            continue
        code, log = run([PY, str(DEV / "expand_bindings.py"), "--ocr", str(ocr_path),
                         "--bindings", str(bind), "--outdir", str(expanded)], timeout=600)
        (work / "expand.log").write_text(log, encoding="utf-8")
        recovered = []
        for path in sorted((expanded / "tables").glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for record in payload.get("records") or []:
                measure = str(record.get("measure") or "")
                category = ""
                source_header = record.get("source_header") or []
                for candidate in reversed(source_header):
                    classified = classify_header(str(candidate))
                    if classified:
                        category = classified[0]
                        break
                if not category:
                    classified = classify_header(measure)
                    category = classified[0] if classified else ""
                if not category:
                    continue
                recovered.append({
                    "record_id": str(record.get("record_id") or "") + "-RB",
                    "channel": "rebind",
                    "category": category,
                    "item": normalize_item(measure)[0] or measure,
                    "grade": str(record.get("grade") or ""),
                    "requirement": str(record.get("requirement") or record.get("raw") or ""),
                    "unit": str(record.get("unit") or ""),
                    "conditions": record.get("conditions") or {},
                    "source_table": record.get("table_id"),
                    "page_no": record.get("page_no"),
                })
        merged = records + recovered
        (work / "merged.json").write_text(json.dumps({"records": merged}, ensure_ascii=False), encoding="utf-8")
        docs_report.append({"doc": doc_dir.name, "candidates": len(table_ids), "recovered": len(recovered),
                            "tables": table_ids})
        print(f"[s11] {doc_dir.name}: candidates={len(table_ids)} recovered={len(recovered)}", flush=True)
    (OUT / "report.json").write_text(json.dumps(docs_report, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(item.get("recovered") or 0 for item in docs_report)
    print(f"[s11] done docs={len(docs_report)} recovered_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
