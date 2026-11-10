"""Select a stratified evaluation corpus from the standards library catalog.

Filters duplicates/cover-only/out-of-range documents, excludes documents that
already have run artifacts, then fills per ``doc_type`` quotas deterministically
(sorted by sha256). The result is a JSON list consumed by ``replay_corpus``.

Usage:
    python -m tools.select_corpus --out runs/corpus_v2/selection.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "standards_library" / "catalog.json"
EXCLUDE_RUNS = (
    ROOT / "runs" / "m2_baseline",
    ROOT / "runs" / "corpus_ext",
    ROOT / "runs" / "corpus_v2",
)

DEFAULT_QUOTAS = {
    "national_or_industry_standard": 10,
    "technical_condition": 50,
    "manufacturing_outline": 30,
    "enterprise_standard": 10,
    "quality_assurance": 10,
    "internal_document": 10,
    "standard_uncertain": 2,
    "uncatalogued": 60,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(CATALOG))
    parser.add_argument("--out", default=str(ROOT / "runs" / "corpus_v2" / "selection.json"))
    parser.add_argument("--min-pages", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    records = catalog.get("records") or []
    seen_sha = _existing_shas()

    candidates = []
    for record in records:
        if record.get("duplicate_of"):
            continue
        pages = int(record.get("pages") or 0)
        if pages < args.min_pages or pages > args.max_pages:
            continue
        sha = str(record.get("sha256") or "")
        if not sha or sha in seen_sha:
            continue
        candidates.append(record)
    candidates.sort(key=lambda item: item["sha256"])

    selected, seen_title, used = [], set(), Counter()
    by_type = defaultdict(list)
    for record in candidates:
        by_type[record.get("doc_type") or "uncatalogued"].append(record)
    for doc_type, quota in DEFAULT_QUOTAS.items():
        for record in by_type.get(doc_type, []):
            if used[doc_type] >= quota:
                break
            title = _norm_title(record.get("title"))
            if title in seen_title:
                continue
            selected.append(_entry(record))
            seen_title.add(title)
            used[doc_type] += 1
    if args.limit:
        selected = selected[: args.limit]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(item["doc_type"] for item in selected)
    print(json.dumps({"selected": len(selected), "by_type": dict(counts)}, ensure_ascii=False))
    print(f"out={out}")
    return 0


def _existing_shas() -> set[str]:
    shas: set[str] = set()
    for runs in EXCLUDE_RUNS:
        if not runs.exists():
            continue
        for manifest in runs.glob("*/manifest.json"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("sha256"):
                shas.add(str(data["sha256"]))
    return shas


def _entry(record: dict) -> dict:
    sha = str(record["sha256"])
    return {
        "file": record["file"],
        "sha256": sha,
        "pages": int(record.get("pages") or 0),
        "title": record.get("title"),
        "doc_type": record.get("doc_type"),
        "slug": f"v2_{sha[:10]}",
    }


def _norm_title(title: str | None) -> str:
    return "".join(str(title or "").split()).lower()


if __name__ == "__main__":
    raise SystemExit(main())
