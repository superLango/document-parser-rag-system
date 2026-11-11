"""Golden-set evaluation for the table pipeline (new vs legacy).

The legacy implementation is imported from the read-only ``legacy/`` archive in
an isolated sys.path entry; it is never imported by production code.

Run from ``new_app``:

    python scripts/benchmark/table_gold_eval.py
"""

import json
import re
import sys
import time
from pathlib import Path

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
GOLDEN_DIR = NEW_APP_DIR / "tests" / "golden" / "table"
LEGACY_ROOT = REPO_ROOT / "legacy" / "metal-doc-agent"

sys.path.insert(0, str(NEW_APP_DIR))

from services.ocr.algorithms.table_grid import extract_tables  # noqa: E402
from services.ocr.contracts import Page  # noqa: E402

REPEATS = 20
METRICS = ("profile", "orientation", "cols", "header_rows", "header_path", "cell")


def normalize(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def evaluate(tables, expect: dict) -> dict:
    exp = expect["expect"][0]
    if not tables:
        return {name: 0.0 for name in METRICS}
    table = tables[0]

    header_total = max(1, exp["n_cols"])
    header_hits = 0
    for index in range(min(exp["n_cols"], len(table.header_paths), len(exp["header_paths"]))):
        actual = [normalize(part) for part in table.header_paths[index]]
        want = [normalize(part) for part in exp["header_paths"][index]]
        if actual == want:
            header_hits += 1

    data_rows = table.rows[table.header_rows :]
    cell_total = 0
    cell_hits = 0
    for row_index, want_row in enumerate(exp["data_rows"]):
        cell_total += len(want_row)
        if row_index >= len(data_rows):
            continue
        actual_row = data_rows[row_index]
        for col_index, want in enumerate(want_row):
            if col_index < len(actual_row) and normalize(actual_row[col_index]) == normalize(want):
                cell_hits += 1

    return {
        "profile": float(table.profile == exp["profile"]),
        "orientation": float(table.orientation == exp["orientation"]),
        "cols": float(table.n_cols == exp["n_cols"]),
        "header_rows": float(table.header_rows == exp["header_rows"]),
        "header_path": header_hits / header_total,
        "cell": cell_hits / cell_total if cell_total else 0.0,
    }


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        cases.append(json.loads(path.read_text(encoding="utf-8")))
    return cases


def run_new(text: str):
    return extract_tables([Page(page_no=1, markdown=text)])


def run_legacy(text: str):
    from metal_doc_agent.contracts import Page as LegacyPage
    from metal_doc_agent.tablegrid.parser import extract_tables as legacy_extract

    return legacy_extract([LegacyPage(page_no=1, markdown=text)])


def latency(func, text: str) -> float:
    started = time.perf_counter()
    for _ in range(REPEATS):
        func(text)
    return (time.perf_counter() - started) / REPEATS * 1000


def main() -> None:
    if str(LEGACY_ROOT) not in sys.path:
        sys.path.append(str(LEGACY_ROOT))

    cases = load_cases()
    if not cases:
        raise SystemExit("no golden cases found")

    rows: list[list[str]] = []
    totals = {"new": {name: 0.0 for name in METRICS}, "legacy": {name: 0.0 for name in METRICS}}
    latencies = {"new": 0.0, "legacy": 0.0}

    for case in cases:
        text = (GOLDEN_DIR / case["source"]).read_text(encoding="utf-8")
        for algo, runner in (("new", run_new), ("legacy", run_legacy)):
            tables = runner(text)
            metrics = evaluate(tables, case)
            for name in METRICS:
                totals[algo][name] += metrics[name]
            rows.append(
                [
                    case["case"],
                    algo,
                    f"{metrics['profile']:.2f}",
                    f"{metrics['orientation']:.2f}",
                    f"{metrics['cols']:.2f}",
                    f"{metrics['header_rows']:.2f}",
                    f"{metrics['header_path']:.3f}",
                    f"{metrics['cell']:.3f}",
                ]
            )
        latencies["new"] += latency(run_new, text)
        latencies["legacy"] += latency(run_legacy, text)

    count = len(cases)
    print("| case | algo | profile | orientation | cols | header_rows | header_path | cell |")
    print("|---|---|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")

    print()
    print("| metric | new | legacy |")
    print("|---|---|---|")
    for name in METRICS:
        new_value = totals["new"][name] / count
        legacy_value = totals["legacy"][name] / count
        print(f"| {name} | {new_value:.4f} | {legacy_value:.4f} |")
    print(f"| latency_ms | {latencies['new'] / count:.2f} | {latencies['legacy'] / count:.2f} |")


if __name__ == "__main__":
    main()
