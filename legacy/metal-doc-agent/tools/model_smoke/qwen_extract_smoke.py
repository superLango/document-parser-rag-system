"""Smoke Qwen extraction on one TableGrid table (optionally one block).

Run from the laptop with QWEN_BASE_URL set:
    python tools/model_smoke/qwen_extract_smoke.py \
      --doc "../标准文件/GBT 40303-2021/..." --table T3 --block-limit 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.extraction.qwen import QwenExtractor
from metal_doc_agent.ingest import ingest
from metal_doc_agent.settings import Settings
from metal_doc_agent.tablegrid.parser import extract_tables


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--block-limit", type=int, default=0)
    args = parser.parse_args()

    document, pages = ingest(args.doc)
    tables = {table.table_id: table for table in extract_tables(pages)}
    table = tables.get(args.table)
    if table is None:
        print("table not found:", sorted(tables))
        return 1
    if args.block_limit:
        table.blocks = table.blocks[: args.block_limit]

    extractor = QwenExtractor(Settings.from_env())
    output = extractor.extract(table, document)
    print("table:", table.table_id, "profile:", table.profile, "blocks:", len(table.blocks))
    print("mapping sources:", extractor.last_mapping_source)
    print("errors:", len(extractor.last_errors))
    for record in output.records:
        print(
            record.grade,
            record.grade_level,
            {key: (value.value, value.lower, value.upper, value.unit, value.comparator)
             for key, value in record.properties.items()},
        )
    print("evidence:", len(output.evidence))
    return 0 if output.records else 1


if __name__ == "__main__":
    raise SystemExit(main())
