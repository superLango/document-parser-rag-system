"""Promote or reject a pending new term."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.canonicalize import (  # noqa: E402
    load_new_terms,
    promote_term,
    reject_term,
    save_new_terms,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--type", default=None, choices=["item", "method"])
    parser.add_argument("--code", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--reject", action="store_true")
    parser.add_argument(
        "--override", default=str(ROOT / "configs" / "business_dictionary.local.json")
    )
    args = parser.parse_args(argv)
    store = load_new_terms(args.terms)
    if args.reject:
        term = reject_term(store, args.raw, args.type)
    else:
        if not args.code:
            parser.error("--code is required unless --reject")
        term = promote_term(
            store,
            args.raw,
            business_code=args.code,
            business_name=args.name,
            override_path=args.override,
            version=store.dictionary_version or None,
            term_type=args.type,
        )
    save_new_terms(store, args.terms)
    print(json.dumps(term.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
