#!/usr/bin/env python3
"""Import the legacy business dictionary into the new canonical snapshot.

Source (default): legacy/metal-doc-agent/configs/dictionaries/*.json
Output: new_app/services/orchestration/data/dictionary/business_dictionary.json

The import is idempotent and resumable at source-file granularity: each source
file is hashed and checkpointed after it is processed, so an interrupted run
skips completed files unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TYPE_ORDER = {"category": 0, "item": 1, "method": 2}
ALLOWED_TYPES = set(TYPE_ORDER)
ALLOWED_STATUS = {"active", "inactive"}
DEFAULT_VERSION = "unknown"
SCHEMA_VERSION = "2.0"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DIR = (
    REPO_ROOT / "legacy" / "metal-doc-agent" / "configs" / "dictionaries"
)
DEFAULT_OUT = (
    REPO_ROOT
    / "new_app"
    / "services"
    / "orchestration"
    / "data"
    / "dictionary"
    / "business_dictionary.json"
)
DEFAULT_REPORT = (
    REPO_ROOT / "new_app" / "docs" / "reports" / "M8-dictionary-import.json"
)
DEFAULT_CHECKPOINT = (
    REPO_ROOT
    / "new_app"
    / "docs"
    / "reports"
    / "M8-dictionary-import.checkpoint.json"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_entry(raw: dict[str, Any], source_name: str) -> dict[str, Any]:
    aliases: list[str] = []
    seen: set[str] = set()
    name = clean(raw.get("business_name"))
    for alias in raw.get("aliases") or []:
        text = clean(alias)
        if not text or text == name or text in seen:
            continue
        seen.add(text)
        aliases.append(text)
    facets = raw.get("facets")
    if not isinstance(facets, dict):
        facets = {}
    return {
        "business_code": clean(raw.get("business_code")),
        "business_name": name,
        "type": clean(raw.get("type")),
        "family": clean(raw.get("family")) or None,
        "facets": facets,
        "aliases": aliases,
        "standard_no": clean(raw.get("standard_no")) or None,
        "category_code": clean(raw.get("category_code")) or None,
        "category_name": clean(raw.get("category_name")) or None,
        "status": clean(raw.get("status")) or "active",
        "version": clean(raw.get("version")),
        "source_file": source_name,
    }


def merge_duplicate(
    existing: dict[str, Any], incoming: dict[str, Any], conflicts: list[dict[str, Any]]
) -> None:
    extra_aliases = list(incoming.get("aliases") or [])
    incoming_name = incoming.get("business_name")
    if incoming_name and incoming_name != existing.get("business_name"):
        extra_aliases.append(incoming_name)
        conflicts.append(
            {
                "code": existing.get("business_code"),
                "type": existing.get("type"),
                "kept": existing.get("business_name"),
                "merged": incoming_name,
                "reason": "DUPLICATE_CODE_MERGED",
            }
        )
    seen = set(existing.get("aliases") or [])
    for alias in extra_aliases:
        if alias and alias not in seen and alias != existing.get("business_name"):
            existing["aliases"].append(alias)
            seen.add(alias)
    for key in ("family", "standard_no", "category_code", "category_name"):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]
    if existing.get("status") == "inactive" and incoming.get("status") == "active":
        existing["status"] = "active"


def load_source(path: Path) -> tuple[list[dict[str, Any]], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{path} has no entries list")
    return [item for item in entries if isinstance(item, dict)], clean(data.get("version"))


def process_source(
    path: Path, entries: list[dict[str, Any]], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        entry = normalize_entry(raw, path.name)
        if entry["type"] not in ALLOWED_TYPES:
            failures.append(
                {
                    "source_file": path.name,
                    "row": index,
                    "code": entry["business_code"],
                    "reason": "INVALID_TYPE",
                    "value": entry["type"],
                }
            )
            continue
        if not entry["business_code"]:
            failures.append(
                {
                    "source_file": path.name,
                    "row": index,
                    "reason": "EMPTY_CODE",
                }
            )
            continue
        if not entry["business_name"]:
            failures.append(
                {
                    "source_file": path.name,
                    "row": index,
                    "code": entry["business_code"],
                    "reason": "EMPTY_NAME",
                }
            )
            continue
        if entry["status"] not in ALLOWED_STATUS:
            failures.append(
                {
                    "source_file": path.name,
                    "row": index,
                    "code": entry["business_code"],
                    "reason": "INVALID_STATUS",
                    "value": entry["status"],
                }
            )
            entry["status"] = "active"
        output.append(entry)
    return output


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "1.0", "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"schema_version": "1.0", "sources": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        return {"schema_version": "1.0", "sources": {}}
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def collect_sources(source_dir: Path, source: Path | None) -> list[Path]:
    if source is not None:
        return [source]
    files = sorted(
        path
        for path in source_dir.glob("*.json")
        if path.name not in {"manifest.json", "business_dictionary.local.json"}
    )
    if not files:
        raise FileNotFoundError(f"no dictionary json found under {source_dir}")
    return files


def import_dictionary(
    *,
    source_dir: Path,
    source: Path | None,
    out: Path,
    report: Path,
    checkpoint_path: Path,
    force: bool,
    check_only: bool,
) -> int:
    started = time.monotonic()
    sources = collect_sources(source_dir, source)
    checkpoint = load_checkpoint(checkpoint_path)
    failures: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    raw_entries_by_source: dict[str, list[dict[str, Any]]] = {}
    completed_sources: dict[str, list[dict[str, Any]]] = {}

    for path in sources:
        data = path.read_bytes()
        digest = sha256_bytes(data)
        cached = checkpoint["sources"].get(str(path))
        if not force and cached and cached.get("sha256") == digest:
            resumed_entries, _ = load_source(path)
            raw_entries_by_source[path.name] = resumed_entries
            completed_sources[path.name] = cached.get("entries") or []
            source_stats.append(
                {
                    "file": path.name,
                    "sha256": digest,
                    "entries": len(completed_sources[path.name]),
                    "source_entries": len(resumed_entries),
                    "resumed": True,
                }
            )
            continue

        entries, version = load_source(path)
        raw_entries_by_source[path.name] = entries
        processed = process_source(path, entries, failures)
        completed_sources[path.name] = processed
        checkpoint["sources"][str(path)] = {
            "sha256": digest,
            "entries": processed,
            "version": version,
        }
        write_json(checkpoint_path, checkpoint)
        source_stats.append(
            {
                "file": path.name,
                "sha256": digest,
                "entries": len(processed),
                "source_entries": len(entries),
                "resumed": False,
            }
        )

    merged: dict[str, dict[str, Any]] = {}
    for source_name in sorted(completed_sources):
        for entry in completed_sources[source_name]:
            code = entry["business_code"]
            existing = merged.get(code)
            if existing is None:
                merged[code] = dict(entry)
                continue
            if existing.get("type") != entry.get("type"):
                failures.append(
                    {
                        "source_file": entry.get("source_file"),
                        "code": code,
                        "reason": "CODE_TYPE_CONFLICT",
                        "kept_type": existing.get("type"),
                        "incoming_type": entry.get("type"),
                    }
                )
                continue
            merge_duplicate(existing, entry, conflicts)

    entries_out = sorted(
        merged.values(),
        key=lambda item: (TYPE_ORDER.get(item.get("type"), 99), item.get("business_code") or ""),
    )
    source_versions = {
        str(Path(path).name): (entry or {}).get("version") if isinstance(entry, dict) else None
        for path, entry in checkpoint["sources"].items()
    }
    versions = sorted({value for value in source_versions.values() if value})
    version = versions[0] if len(versions) == 1 else "mixed"
    if not version or version == "None":
        version = DEFAULT_VERSION

    type_counts = Counter(item["type"] for item in entries_out)
    status_counts = Counter(item["status"] for item in entries_out)
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source": "legacy:metal-doc-agent/configs/dictionaries",
        "source_files": sorted(completed_sources),
        "stats": {
            "entries": len(entries_out),
            "categories": type_counts.get("category", 0),
            "items": type_counts.get("item", 0),
            "methods": type_counts.get("method", 0),
            "aliases": sum(len(item.get("aliases") or []) for item in entries_out),
            "active": status_counts.get("active", 0),
            "inactive": status_counts.get("inactive", 0),
        },
        "entries": entries_out,
    }

    reconciliation = reconcile(
        source_entries={name: entries for name, entries in completed_sources.items()},
        output_entries=entries_out,
        raw_entries=raw_entries_by_source,
        conflicts=conflicts,
        failures=failures,
    )

    report_payload = {
        "generated_at": now_iso(),
        "duration_seconds": round(time.monotonic() - started, 2),
        "source_dir": str(source_dir),
        "source": str(source) if source else None,
        "output": str(out),
        "version": version,
        "stats": canonical["stats"],
        "source_stats": source_stats,
        "conflicts": conflicts,
        "failures": failures,
        "reconciliation": reconciliation,
        "checkpoint": str(checkpoint_path),
        "check_only": check_only,
    }

    if not check_only:
        write_json(out, canonical)
        digest = sha256_bytes(json.dumps(canonical, ensure_ascii=False).encode("utf-8"))
        write_json(
            out.with_name("manifest.json"),
            {
                "schema_version": SCHEMA_VERSION,
                "version": version,
                "sha256": digest,
                "stats": canonical["stats"],
                "source_files": canonical["source_files"],
                "generated_at": now_iso(),
            },
        )
    write_json(report, report_payload)

    print(
        json.dumps(
            {
                "ok": not reconciliation["missing_codes"] and not reconciliation["extra_codes"],
                "mode": "check" if check_only else "import",
                "output": str(out),
                "report": str(report),
                "stats": canonical["stats"],
                "conflicts": len(conflicts),
                "failures": len(failures),
                "missing_codes": len(reconciliation["missing_codes"]),
                "extra_codes": len(reconciliation["extra_codes"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not reconciliation["missing_codes"] and not reconciliation["extra_codes"] else 1


def reconcile(
    *,
    source_entries: dict[str, list[dict[str, Any]]],
    output_entries: list[dict[str, Any]],
    raw_entries: dict[str, list[dict[str, Any]]],
    conflicts: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    source_flat = [entry for entries in source_entries.values() for entry in entries]
    source_codes = {entry["business_code"] for entry in source_flat}
    output_codes = {entry["business_code"] for entry in output_entries}
    raw_types = Counter(
        entry.get("type") for entries in raw_entries.values() for entry in entries
    )
    output_types = Counter(entry["type"] for entry in output_entries)

    source_by_code = {entry["business_code"]: entry for entry in source_flat}
    alias_diffs: list[dict[str, Any]] = []
    status_diffs: list[dict[str, Any]] = []
    for entry in output_entries:
        source = source_by_code.get(entry["business_code"])
        if source is None:
            continue
        source_aliases = sorted(set(source.get("aliases") or []))
        output_aliases = sorted(set(entry.get("aliases") or []))
        if source_aliases != output_aliases:
            alias_diffs.append(
                {
                    "code": entry["business_code"],
                    "source": source_aliases,
                    "output": output_aliases,
                }
            )
        if source.get("status") != entry.get("status"):
            status_diffs.append(
                {
                    "code": entry["business_code"],
                    "source": source.get("status"),
                    "output": entry.get("status"),
                }
            )

    return {
        "source_entries": len(source_flat),
        "output_entries": len(output_entries),
        "source_unique_codes": len(source_codes),
        "output_codes": len(output_codes),
        "missing_codes": sorted(source_codes - output_codes),
        "extra_codes": sorted(output_codes - source_codes),
        "source_types": dict(sorted(raw_types.items(), key=lambda item: str(item[0]))),
        "output_types": dict(sorted(output_types.items())),
        "duplicate_codes": sorted(
            {item["code"] for item in conflicts if item.get("reason") == "DUPLICATE_CODE_MERGED"}
        ),
        "failures": len(failures),
        "alias_diffs": alias_diffs[:100],
        "alias_diff_count": len(alias_diffs),
        "status_diffs": status_diffs[:100],
        "status_diff_count": len(status_diffs),
        "alias_total": sum(len(item.get("aliases") or []) for item in output_entries),
        "status_counts": dict(
            sorted(Counter(item["status"] for item in output_entries).items())
        ),
        "verdict": (
            "pass"
            if not (source_codes - output_codes)
            and not (output_codes - source_codes)
            and not status_diffs
            else "review"
        ),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--force", action="store_true", help="ignore checkpoint")
    parser.add_argument("--check", action="store_true", help="validate only; do not write output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return import_dictionary(
        source_dir=args.source_dir,
        source=args.source,
        out=args.out,
        report=args.report,
        checkpoint_path=args.checkpoint,
        force=args.force,
        check_only=args.check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
