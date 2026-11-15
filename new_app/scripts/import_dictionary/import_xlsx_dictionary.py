#!/usr/bin/env python3
"""Import the business dictionary from an xlsx sheet (FEATURE / ITEM_NAME / METHOD_CODE).

Usage (from new_app):
    python scripts/import_dictionary/import_xlsx_dictionary.py --source path/to/dict.xlsx

The import merges into the canonical snapshot:
* ``FEATURE``      -> category entries (existing aliases/family preserved)
* ``ITEM_NAME``    -> item entries, tagged with the owning category
* ``METHOD_CODE``  -> method entries, one per edition (latest edition wins at match time)

Standard library only: the sheet is read through ``zipfile`` + ``xml.etree`` so the
script runs where openpyxl is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = (
    APP_ROOT
    / "services"
    / "orchestration"
    / "data"
    / "dictionary"
    / "business_dictionary.json"
)
MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = "2.0"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TEXT_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
ROW_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"
CELL_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
VALUE_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v"

# Standard prefixes: keep the slash form stable so ``GB/T`` and ``GBT`` converge.
PREFIX_ALIASES = {
    "GBT": "GB/T",
    "GB": "GB",
    "GJB": "GJB",
    "JBT": "JB/T",
    "JB": "JB",
    "YBT": "YB/T",
    "YB": "YB",
    "YST": "YS/T",
    "YS": "YS",
    "HBT": "HB/T",
    "HB": "HB",
    "ASTM": "ASTM",
    "ASME": "ASME",
    "AMS": "AMS",
    "ISO": "ISO",
    "EN": "EN",
    "DIN": "DIN",
    "JIS": "JIS",
    "SAE": "SAE",
    "API": "API",
    "MIL": "MIL",
    "NB": "NB",
    "Q/HT": "Q/HT",
    "JY/T": "JY/T",
}
STANDARD_RE = re.compile(
    r"^([A-Za-z]+(?:/[A-Za-z]+)?)\s*([A-Z]{0,3})\s*(-?)\s*(\d[\d.]*)"
    r"([A-Za-z])?\s*(?:[-—–－]\s*(\d{2,4}))?([A-Za-z])?$"
)
# One METHOD_CODE cell may carry several standards ("GB/T 5168-2020,GB/T 13298-2015").
METHOD_TOKEN_RE = re.compile(
    r"(GB\s*/\s*T|GB|GJB|JB\s*/\s*T|JB|YB\s*/\s*T|YB|YS\s*/\s*T|HB\s*/\s*T|HB|"
    r"ASTM|ASME|AMS|AETM|ISO|EN|DIN|JIS|SAE|API|MIL|NB|Q\s*/\s*HT|JY\s*/\s*T)"
    r"\s*([A-Z]{0,3})\s*(-?)\s*(\d[\d.]*)"
    r"([A-Za-z])?\s*(?:[-—–－]\s*(\d{2,4}))?([A-Za-z])?",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def normalize_standard(code: str) -> tuple[str, str, int]:
    """Return ``(standard_no, base_no, edition_year)``.

    ``base_no`` drops the edition year; ``edition_year`` is 0 when unknown.
    """
    text = clean(code).replace("—", "-").replace("–", "-").replace("－", "-")
    text = re.sub(r"\s*/\s*", "/", text)
    match = STANDARD_RE.match(text)
    if not match:
        return text, text, 0
    prefix_raw, letter, dash, number, revision, year, tail = match.groups()
    prefix = PREFIX_ALIASES.get(prefix_raw.upper(), prefix_raw.upper())
    core = f"{prefix} {letter.upper()}{dash}{number}"
    if revision:
        core = f"{core}{revision}"
    edition = 0
    standard_no = core
    if year:
        edition = int(year)
        if len(year) == 2:
            edition += 1900 if edition >= 70 else 2000
        standard_no = f"{core}-{edition}"
    if tail:
        standard_no = f"{standard_no}{tail}"
    return standard_no, core, edition


def extract_standards(text: str) -> list[str]:
    """Split one METHOD_CODE cell into normalized standard numbers."""
    cleaned = (
        clean(text).replace("—", "-").replace("–", "-").replace("－", "-")
    )
    found: list[str] = []
    for match in METHOD_TOKEN_RE.finditer(cleaned):
        standard_no, _base, _edition = normalize_standard(match.group(0))
        if standard_no and standard_no not in found:
            found.append(standard_no)
    return found


def column_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(1):
        index = index * 26 + ord(char) - 64
    return index - 1


def read_xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for node in root.findall("m:si", NS):
                shared.append("".join(item.text or "" for item in node.iter(TEXT_TAG)))
        sheet_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_names:
            raise ValueError(f"{path} has no worksheet")
        root = ElementTree.fromstring(archive.read(sheet_names[0]))
        rows: list[list[str]] = []
        for node in root.iter(ROW_TAG):
            cells: dict[int, str] = {}
            for cell in node.findall("m:c", NS):
                value = cell.find("m:v", NS)
                if value is None or value.text is None:
                    continue
                text = value.text
                if cell.get("t") == "s":
                    text = shared[int(text)]
                cells[column_index(cell.get("r") or "")] = clean(text)
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(index, "") for index in range(width)])
        return rows


def read_sheet(path: Path) -> list[dict[str, str]]:
    rows = read_xlsx_rows(path)
    if not rows:
        return []
    header = [clean(value).upper() for value in rows[0]]
    index = {name: position for position, name in enumerate(header)}
    for required in ("FEATURE", "ITEM_NAME", "METHOD_CODE"):
        if required not in index:
            raise ValueError(f"{path} is missing column {required}: {header}")
    output: list[dict[str, str]] = []

    def cell(row: list[str], name: str) -> str:
        position = index[name]
        return clean(row[position]) if position < len(row) else ""

    for row in rows[1:]:
        feature = cell(row, "FEATURE")
        item = cell(row, "ITEM_NAME")
        method = cell(row, "METHOD_CODE")
        if not (feature or item or method):
            continue
        output.append({"feature": feature, "item": item, "method": method})
    return output


def entry_key(kind: str, name: str) -> tuple[str, str]:
    return kind, re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).lower()


def merge_aliases(entry: dict[str, Any], *names: str) -> None:
    current = list(entry.get("aliases") or [])
    seen = {str(alias) for alias in current}
    base_name = str(entry.get("business_name") or "")
    for name in names:
        text = clean(name)
        if not text or text == base_name or text in seen:
            continue
        seen.add(text)
        current.append(text)
    entry["aliases"] = current


def next_code(entries: list[dict[str, Any]], kind: str) -> int:
    top = 0
    prefix = f"{kind.upper()}:"
    for entry in entries:
        code = str(entry.get("business_code") or "")
        if code.startswith(prefix):
            try:
                top = max(top, int(code[len(prefix):]))
            except ValueError:
                continue
    return top + 1


def build(
    source: Path, out: Path, replace: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = source.read_bytes()
    version = f"hanson-ht-xlsx-{hashlib.sha256(raw).hexdigest()[:8]}"
    current = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    entries: list[dict[str, Any]] = [] if replace else [
        item for item in current.get("entries") or [] if isinstance(item, dict)
    ]
    categories = {
        entry_key("category", str(entry.get("business_name") or "")): entry
        for entry in entries
        if entry.get("type") == "category"
    }
    items = {
        entry_key("item", str(entry.get("business_name") or "")): entry
        for entry in entries
        if entry.get("type") == "item"
    }
    methods = {
        entry_key("method", str(entry.get("standard_no") or "")): entry
        for entry in entries
        if entry.get("type") == "method" and entry.get("standard_no")
    }
    counters = {kind: next_code(entries, kind) for kind in ("category", "item", "method")}
    stats = Counter()
    touched: set[str] = set()
    samples: dict[str, list[str]] = {"features": [], "items": [], "methods": []}

    def add(
        kind: str,
        name: str,
        **fields: Any,
    ) -> dict[str, Any]:
        entry = {
            "business_code": f"{kind.upper()}:{counters[kind]}",
            "business_name": name,
            "type": kind,
            "family": None,
            "facets": {},
            "aliases": [],
            "standard_no": None,
            "category_code": None,
            "category_name": None,
            "status": "active",
            "version": version,
            "source_file": source.name,
            **fields,
        }
        counters[kind] += 1
        entries.append(entry)
        stats[f"created_{kind}"] += 1
        return entry

    def touch(entry: dict[str, Any]) -> None:
        entry["status"] = "active"
        entry["version"] = version
        touched.add(str(entry.get("business_code") or ""))

    for row in read_sheet(source):
        feature = row["feature"]
        item = row["item"]
        method = row["method"]
        category_entry: dict[str, Any] | None = None
        if feature:
            key = entry_key("category", feature)
            category_entry = categories.get(key)
            if category_entry is None:
                category_entry = add("category", feature)
                categories[key] = category_entry
                if len(samples["features"]) < 8:
                    samples["features"].append(feature)
            else:
                touch(category_entry)
        if item and feature:
            key = entry_key("item", item)
            item_entry = items.get(key)
            if item_entry is None:
                item_entry = add(
                    "item",
                    item,
                    category_name=feature,
                    family=(category_entry or {}).get("family"),
                    category_code=(category_entry or {}).get("business_code"),
                )
                items[key] = item_entry
                if len(samples["items"]) < 8:
                    samples["items"].append(f"{feature}/{item}")
            else:
                touch(item_entry)
                merge_aliases(item_entry, item)
                if not item_entry.get("category_name"):
                    item_entry["category_name"] = feature
        if method:
            standards = extract_standards(method) or (
                [clean(method)] if re.search(r"[0-9A-Za-z]", method) else []
            )
            for standard_no in standards:
                key = entry_key("method", standard_no)
                method_entry = methods.get(key)
                if method_entry is None:
                    method_entry = add(
                        "method",
                        standard_no,
                        standard_no=standard_no,
                        family=(category_entry or {}).get("family"),
                    )
                    methods[key] = method_entry
                    if len(samples["methods"]) < 8:
                        samples["methods"].append(
                            standard_no
                            if standard_no == clean(method)
                            else f"{standard_no} ({method})"
                        )
                else:
                    touch(method_entry)
                    merge_aliases(method_entry, clean(method))
                    # 统一标准号写法（"GB/T5168-2020" -> "GB/T 5168-2020"）。
                    if standard_no != str(method_entry.get("standard_no") or ""):
                        method_entry["standard_no"] = standard_no

    entries.sort(
        key=lambda entry: (
            {"category": 0, "item": 1, "method": 2}.get(entry.get("type"), 9),
            str(entry.get("business_code") or ""),
        )
    )
    type_counts = Counter(entry.get("type") for entry in entries)
    status_counts = Counter(entry.get("status") for entry in entries)
    source_files = sorted(
        {
            *[str(name) for name in current.get("source_files") or []],
            source.name,
        }
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source": current.get("source") or "xlsx-import",
        "source_files": source_files,
        "stats": {
            "entries": len(entries),
            "categories": type_counts.get("category", 0),
            "items": type_counts.get("item", 0),
            "methods": type_counts.get("method", 0),
            "aliases": sum(len(entry.get("aliases") or []) for entry in entries),
            "active": status_counts.get("active", 0),
            "inactive": status_counts.get("inactive", 0),
        },
        "entries": entries,
    }
    report = {
        "source": str(source),
        "output": str(out),
        "version": version,
        "rows": len(read_sheet(source)),
        "changes": {**dict(stats), "updated": len(touched)},
        "samples": samples,
        "stats": payload["stats"],
    }
    return payload, report


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="drop existing entries instead of merging",
    )
    parser.add_argument(
        "--check", action="store_true", help="build the report without writing"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.source.exists():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 2
    payload, report = build(args.source, args.out, args.replace)
    if not args.check:
        write_json(args.out, payload)
        write_json(
            args.out.with_name(MANIFEST_NAME),
            {
                "schema_version": SCHEMA_VERSION,
                "version": payload["version"],
                "sha256": hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "stats": payload["stats"],
                "source_files": payload["source_files"],
                "generated_at": now_iso(),
            },
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
