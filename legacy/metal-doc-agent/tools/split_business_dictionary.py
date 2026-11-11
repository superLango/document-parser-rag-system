"""Split the legacy mixed business dictionary into three independent files.

Usage:
    python tools/split_business_dictionary.py \
        --base configs/business_dictionary.hanson.json \
        --override configs/business_dictionary.local.json \
        --out configs/dictionaries
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.canonicalize.dictionary import (  # noqa: E402
    JsonDictionaryAdapter,
    write_dictionary_parts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=ROOT / "configs" / "business_dictionary.hanson.json",
    )
    parser.add_argument(
        "--override",
        type=Path,
        default=ROOT / "configs" / "business_dictionary.local.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "configs" / "dictionaries",
    )
    parser.add_argument("--version", default=None)
    args = parser.parse_args()

    override = args.override if args.override.exists() else None
    dictionary = JsonDictionaryAdapter(args.base, override).load()
    paths = write_dictionary_parts(args.out, dictionary, version=args.version)
    print(f"version={dictionary.version} entries={len(dictionary.entries)}")
    for entry_type, path in paths.items():
        print(f"{entry_type}: {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
