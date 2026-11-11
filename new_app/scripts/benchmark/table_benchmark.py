"""Deterministic table pipeline benchmark.

Measures parse latency and output stability for the OCR table pipeline over the
local fixtures. Run from ``new_app``:

    python scripts/benchmark/table_benchmark.py
"""

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

NEW_APP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP_DIR))

from services.ocr.algorithms.table_grid import extract_tables  # noqa: E402
from services.ocr.contracts import Page  # noqa: E402

FIXTURES = sorted((NEW_APP_DIR / "tests" / "fixtures" / "ocr").glob("*.md"))
REPEATS = 50


def _digest(tables) -> str:
    payload = json.dumps(
        [table.model_dump() for table in tables], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    if not FIXTURES:
        raise SystemExit("no fixtures found")

    rows: list[str] = []
    for fixture in FIXTURES:
        text = fixture.read_text(encoding="utf-8")
        pages = [Page(page_no=1, markdown=text)]
        samples: list[float] = []
        digests: set[str] = set()
        tables = []
        for _ in range(REPEATS):
            started = time.perf_counter()
            tables = extract_tables(pages)
            samples.append((time.perf_counter() - started) * 1000)
            digests.add(_digest(tables))

        ordered = sorted(samples)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
        deterministic = len(digests) == 1
        for table in tables:
            rows.append(
                f"| {fixture.name} | {table.table_id} | {table.profile} | "
                f"{table.n_rows} | {table.n_cols} | {table.header_rows} |"
            )
        print(
            f"{fixture.name}: repeats={REPEATS} "
            f"mean={statistics.mean(samples):.2f}ms "
            f"p95={p95:.2f}ms deterministic={deterministic} "
            f"tables={len(tables)}"
        )

    print()
    print("| fixture | table | profile | rows | cols | header_rows |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
