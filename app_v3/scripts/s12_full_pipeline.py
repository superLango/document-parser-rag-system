"""S12 全链路试点：在冻结口径文档上重跑 v2 全流程（bind→expand→enrich→assemble）。

与 S11 不同：不自行做类别映射，完整复用 v2 下游链路；只用于少量高潜力文档。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / "new_app" / ".venv" / "Scripts" / "python.exe")
DEV = ROOT / "new_app" / "scripts" / "dev"
BASE = ROOT / ".tmp" / "batch20"
OUT = ROOT / ".tmp" / "s12_full"
REMOTE = "grainuser@192.168.1.35"
DOCS = ["gbt-8547-2019", "xx454-2022", "hb-20079-2012"]


def run(cmd: list[str], timeout: int, log_path: Path) -> tuple[int, float, str]:
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=str(ROOT))
        output = (proc.stdout or "") + "\n---stderr---\n" + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = f"TIMEOUT {timeout}s\n{exc.stdout or ''}\n{exc.stderr or ''}"
        code = 124
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    return code, round(time.time() - started, 1), output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", default=",".join(DOCS))
    parser.add_argument("--min-cols", type=int, default=2)
    args = parser.parse_args()
    docs = [item.strip() for item in args.docs.split(",") if item.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for doc in docs:
        ocr = BASE / doc / "ocr" / "ocr.json"
        if not ocr.exists():
            report.append({"doc": doc, "error": "missing_ocr"})
            continue
        work = OUT / doc
        bind = work / "bind"
        expanded = work / "expanded"
        enriched = work / "enriched"
        assembled = work / "assembled"
        timings = {}
        code, timings["bind"], _ = run([
            PY, str(DEV / "dsh_bind_v2.py"), "--ocr", str(ocr), "--auto",
            "--outdir", str(bind), "--vote", "1", "--concurrency", "6",
            "--min-cols", str(args.min_cols), "--timeout", "120",
            "--skip-profiles", "", "--remote", REMOTE,
        ], 1200, work / "bind.log")
        if code != 0:
            report.append({"doc": doc, "error": "bind_failed", "timings": timings})
            continue
        code, timings["expand"], _ = run([PY, str(DEV / "expand_bindings.py"),
                                          "--ocr", str(ocr), "--bindings", str(bind),
                                          "--outdir", str(expanded)], 600, work / "expand.log")
        code, timings["enrich"], _ = run([PY, str(DEV / "dsh_enrich.py"),
                                          "--ocr", str(ocr), "--bindings", str(expanded),
                                          "--outdir", str(enriched), "--filename", f"{doc}.pdf"],
                                         600, work / "enrich.log")
        code, timings["assemble"], _ = run([PY, str(DEV / "dsh_assemble.py"),
                                            "--ocr", str(ocr), "--bindings", str(expanded),
                                            "--enrich", str(enriched), "--outdir", str(assembled)],
                                           600, work / "assemble.log")
        records = 0
        if (assembled / "assembly-report.json").exists():
            records = len(json.loads((assembled / "assembly-report.json").read_text(encoding="utf-8")).get("records") or [])
        report.append({"doc": doc, "records": records, "timings": timings})
        print(f"[s12] {doc}: records={records} timings={timings}", flush=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
