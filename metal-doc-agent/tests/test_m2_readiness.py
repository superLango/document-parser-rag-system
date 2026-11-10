import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "m2_readiness", ROOT / "tools" / "m2_readiness.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_manifest(gold: Path, docs: list[dict]) -> None:
    (gold / "docs").mkdir(parents=True, exist_ok=True)
    (gold / "manifest.json").write_text(
        json.dumps(
            {"goldset_version": "v0", "documents": docs}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    for doc in docs:
        annotation = doc.get("annotation_file")
        if not annotation:
            continue
        (gold / annotation).write_text(
            json.dumps(
                {
                    "tables": [
                        {"table_id": "T1", "profile": "inspection"},
                        {"table_id": "T2", "profile": "mechanical_properties"},
                        {"table_id": "T3", "profile": "chemical_composition"},
                    ]
                }
            ),
            encoding="utf-8",
        )


def write_dataset(dataset: Path, heldout_rows: list[dict] | None = None) -> None:
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / "report.json").write_text(
        json.dumps(
            {
                "samples": {
                    "train": {"header_mapping": 1},
                    "dev": {"row_record": 1},
                    "heldout": {"clause_extract": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    rows = {
        "train": [
            {
                "task": "header_mapping",
                "doc_id": "a",
                "input": {"header_paths": [["牌号"]]},
                "meta": {},
            }
        ],
        "dev": [
            {
                "task": "row_record",
                "doc_id": "b",
                "input": {"row": ["430"]},
                "meta": {"row_index": 1},
            }
        ],
        "heldout": heldout_rows
        or [
            {
                "task": "clause_extract",
                "doc_id": "d",
                "input": {"quotes": ["原文"]},
                "meta": {},
            }
        ],
    }
    for split, items in rows.items():
        (dataset / f"{split}.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
            encoding="utf-8",
        )


class ReadinessTests(unittest.TestCase):
    def _setup(self, docs: list[dict], heldout_rows=None):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        gold = root / "gold"
        dataset = root / "dataset"
        write_manifest(gold, docs)
        write_dataset(dataset, heldout_rows)
        return tmp, gold, dataset

    def test_clean_split_passes(self) -> None:
        docs = [
            {"doc_id": "a", "standard_no": "GB/T 1-2000", "split": "mini", "doc_type": "gb_t"},
            {"doc_id": "b", "standard_no": "GB/T 2-2000", "split": "dev", "doc_type": "gjb"},
            {"doc_id": "c", "standard_no": "GB/T 3-2010", "split": "dev", "doc_type": "gjb"},
            {
                "doc_id": "d",
                "standard_no": "Q/A 1-2019",
                "split": "heldout",
                "doc_type": "enterprise",
                "annotation_file": "docs/d.json",
            },
        ]
        tmp, gold, dataset = self._setup(docs)
        try:
            result = module.build_readiness(gold, dataset)
            self.assertEqual(result["status"], "pass")
            checks = {item["id"]: item["status"] for item in result["checks"]}
            self.assertEqual(checks["leakage"], "pass")
            self.assertEqual(checks["family_split"], "pass")
            self.assertEqual(checks["heldout_purity"], "pass")
            self.assertEqual(checks["traceability"], "pass")
        finally:
            tmp.cleanup()

    def test_family_split_conflict_fails(self) -> None:
        docs = [
            {"doc_id": "b", "standard_no": "GB/T 2-2000", "split": "dev", "doc_type": "gb_t"},
            {"doc_id": "c", "standard_no": "GB/T 2-2010", "split": "heldout", "doc_type": "gb_t"},
        ]
        tmp, gold, dataset = self._setup(docs)
        try:
            result = module.build_readiness(gold, dataset)
            checks = {item["id"]: item["status"] for item in result["checks"]}
            self.assertEqual(checks["family_split"], "fail")
            self.assertEqual(result["status"], "fail")
        finally:
            tmp.cleanup()

    def test_heldout_perturbation_fails(self) -> None:
        docs = [
            {"doc_id": "d", "standard_no": "Q/A 1-2019", "split": "heldout", "doc_type": "enterprise"}
        ]
        rows = [
            {
                "task": "row_record_perturb",
                "doc_id": "d",
                "input": {"row": ["4 30"]},
                "meta": {"row_index": 1},
            }
        ]
        tmp, gold, dataset = self._setup(docs, rows)
        try:
            result = module.build_readiness(gold, dataset)
            checks = {item["id"]: item["status"] for item in result["checks"]}
            self.assertEqual(checks["heldout_purity"], "fail")
            self.assertEqual(result["status"], "fail")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
