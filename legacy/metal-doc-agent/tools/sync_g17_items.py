"""Sync G1.7 item gold from the current ItemInventory predictions (v0 sample)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from metal_doc_agent.contracts import ItemInventory  # noqa: E402
from run_loader import load_run  # noqa: E402
from seed_g17_gold import _items  # noqa: E402

MANUAL_ITEMS = {
    "qdu302_2015",
    "gbt40303_2021",
    "gbt3880_1_2012",
    "jx25_035",
    "gjb2057a_2018",
}


def main() -> int:
    gold_dir = ROOT / "goldset" / "g1_7" / "v0"
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    for doc in manifest["docs"]:
        if doc["doc_id"] in MANUAL_ITEMS:
            continue
        run = load_run(ROOT / "runs" / "m1.5_qwen" / doc.get("run", doc["doc_id"]))
        inventory = ItemInventory.model_validate_json(
            (run.run_dir / "item_inventory.json").read_text(encoding="utf-8")
        )
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        items, unknown = _items(doc["doc_id"], inventory, None)
        gold["items"] = items
        gold["items_unknown_ok"] = unknown
        (gold_dir / doc["file"]).write_text(
            json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{doc['doc_id']}: items={len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
