#!/usr/bin/env python3
"""Promote repeated verified cases into the hash-protected learned overlay.

The production concept dictionary and recipes are never modified; only the
overlay file is written.  Consumers ignore the overlay when its sha256 does not
match the content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from services.orchestration.feedback.memory import CaseStore  # noqa: E402
from services.orchestration.feedback.promotion import (  # noqa: E402
    DEFAULT_MIN_HITS,
    OverlayStore,
    build_overlay,
    save_overlay,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--min-hits", type=int, default=DEFAULT_MIN_HITS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases_path = Path(args.cases) if args.cases else CaseStore().path
    out_path = Path(args.out) if args.out else OverlayStore().path
    cases = CaseStore(cases_path).load()
    payload = build_overlay(cases, min_hits=args.min_hits)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "promoted": len(payload["entries"]),
                "min_hits": args.min_hits,
                "sha256": payload["sha256"],
                "out": str(out_path),
            },
            ensure_ascii=False,
        )
    )
    if args.dry_run:
        return 0
    save_overlay(out_path, payload)
    print(f"overlay written: {out_path}")
    print(
        "set HANSON_LEARNED_OVERLAY="
        + os.fspath(out_path)
        + " for services that use a different path"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
