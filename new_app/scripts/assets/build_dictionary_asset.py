"""Build the sandbox dictionary snapshot from the business dictionary.

Usage (from new_app):
    python scripts/assets/build_dictionary_asset.py

The source is the orchestration dictionary (2203 entries: item / method /
category).  The sandbox only needs names, aliases, family/category and standard
numbers, so the snapshot strips codes/facets and stays well below the parser
bundle size limit.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    APP_ROOT
    / "services"
    / "orchestration"
    / "data"
    / "dictionary"
    / "business_dictionary.json"
)
TARGET = APP_ROOT / "services" / "sandbox" / "runtime" / "dictionary_data.json"


def _compact(entry: dict) -> dict:
    name = str(entry.get("business_name") or "").strip()
    aliases = [
        str(alias).strip()
        for alias in entry.get("aliases") or []
        if str(alias).strip()
    ]
    # "断后伸长率(A)" also answers to the printed symbol "A"/"Z".
    for group in re.findall(r"[（(]([^）)]{1,16})[）)]", name):
        for part in re.split(r"[,，/、\s]+", group):
            value = part.strip()
            if value and value not in aliases and value != name:
                aliases.append(value)
    # "晶粒度Average Grain Size" also answers to its Chinese head "晶粒度".
    latin = re.search(r"[\u4e00-\u9fff]([A-Za-z][A-Za-z\s]+)$", name)
    if latin:
        head = name[: latin.start(1)].strip()
        if len(head) >= 2 and head not in aliases:
            aliases.append(head)
    payload = {
        "name": name,
        "aliases": aliases,
        "family": entry.get("family") or "",
    }
    if entry.get("type") == "item":
        payload["category"] = entry.get("category_name") or ""
    if entry.get("type") == "method":
        payload["standard_no"] = entry.get("standard_no") or ""
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    snapshot = {
        "schema_version": "business-dictionary/1",
        "version": str(payload.get("version") or ""),
        "source": str(payload.get("source") or "business_dictionary"),
        "categories": [],
        "items": [],
        "methods": [],
    }
    skipped = 0
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("status") not in {None, "active"}:
            skipped += 1
            continue
        kind = str(entry.get("type") or "")
        name = str(entry.get("business_name") or "").strip()
        if not name:
            skipped += 1
            continue
        if kind == "category":
            snapshot["categories"].append(_compact(entry))
        elif kind == "item":
            snapshot["items"].append(_compact(entry))
        elif kind == "method":
            if not str(entry.get("standard_no") or "").strip() and not name:
                skipped += 1
                continue
            snapshot["methods"].append(_compact(entry))
        else:
            skipped += 1
    snapshot["stats"] = {
        "categories": len(snapshot["categories"]),
        "items": len(snapshot["items"]),
        "methods": len(snapshot["methods"]),
        "skipped": skipped,
    }
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.target} "
        f"({args.target.stat().st_size} bytes) "
        f"categories={snapshot['stats']['categories']} "
        f"items={snapshot['stats']['items']} "
        f"methods={snapshot['stats']['methods']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
