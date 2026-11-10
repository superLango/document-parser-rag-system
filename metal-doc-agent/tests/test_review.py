import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.canonicalize import (
    find_new_term,
    reapply_alignment,
    review_new_term,
)
from metal_doc_agent.canonicalize.terms import load_new_terms, save_new_terms
from metal_doc_agent.contracts import (
    BusinessDictionary,
    BusinessDictionaryEntry,
    ItemInventory,
    ItemInventoryEntry,
    NewTermStore,
)


def _inventory(raw: str, family: str = "inspection") -> ItemInventory:
    return ItemInventory(
        doc_id="doc",
        items=[
            ItemInventoryEntry(
                item_raw=raw,
                item_canonical=raw,
                item_family=family,
                evidence=["ev:1"],
            )
        ],
    )


def _align_and_store(
    out_dir: Path,
    dictionary: BusinessDictionary,
    raw: str = "发货检验",
    family: str = "inspection",
):
    inventory = _inventory(raw, family)
    (out_dir / "item_inventory.json").write_text(
        json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    from metal_doc_agent.canonicalize import DictionaryIndex, align_inventory

    _, result = align_inventory(inventory, DictionaryIndex.build(dictionary))
    save_new_terms(
        NewTermStore(dictionary_version=dictionary.version, terms=result.new_terms),
        out_dir / "new_terms.json",
    )
    return result


class ReviewFlowTests(unittest.TestCase):
    def test_accept_writes_override_and_reapplies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dictionary = BusinessDictionary(version="test-v1", entries=[])
            result = _align_and_store(root, dictionary)
            store = load_new_terms(root / "new_terms.json")
            term = find_new_term(store, "item", "发货检验")
            self.assertIsNotNone(term)
            self.assertEqual(result.item_matches[0].status, "new")

            merged, code, status = review_new_term(
                dictionary,
                root / "dictionary.local.json",
                term,
                "accept",
                business_code="LOCAL:SHIP",
                business_name="发货检验",
            )
            self.assertEqual(status, "active")
            self.assertEqual(code, "LOCAL:SHIP")
            self.assertTrue((root / "dictionary.local.json").exists())

            refresh, updated = reapply_alignment(root, merged)
            self.assertEqual(refresh.item_matches[0].canonical_id, "LOCAL:SHIP")
            self.assertEqual(refresh.item_matches[0].status, "matched")
            self.assertEqual(updated.terms, [])

    def test_map_adds_alias_to_existing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dictionary = BusinessDictionary(
                version="test-v1",
                entries=[
                    BusinessDictionaryEntry(
                        business_code="ITEM_EXIST",
                        business_name="已存在项目",
                        type="item",
                        family="inspection",
                    )
                ],
            )
            _align_and_store(root, dictionary, family="unknown")
            store = load_new_terms(root / "new_terms.json")
            term = find_new_term(store, "item", "发货检验")
            self.assertIsNotNone(term)
            merged, code, _ = review_new_term(
                dictionary,
                root / "dictionary.local.json",
                term,
                "map",
                target_code="ITEM_EXIST",
            )
            self.assertEqual(code, "ITEM_EXIST")
            refresh, _ = reapply_alignment(root, merged)
            self.assertEqual(refresh.item_matches[0].canonical_id, "ITEM_EXIST")

    def test_accept_generates_local_code(self) -> None:
        dictionary = BusinessDictionary(version="test-v1", entries=[])
        from metal_doc_agent.contracts import NewTerm

        term = NewTerm(type="item", raw="发货检验", family="inspection")
        with tempfile.TemporaryDirectory() as tmp:
            merged, code, _ = review_new_term(
                dictionary, Path(tmp) / "local.json", term, "accept"
            )
        self.assertTrue(code.startswith("LOCAL:ITEM:"))
        self.assertEqual(merged.entries[-1].business_code, code)

    def test_reject_keeps_dictionary(self) -> None:
        dictionary = BusinessDictionary(version="test-v1", entries=[])
        from metal_doc_agent.contracts import NewTerm

        term = NewTerm(type="item", raw="发货检验")
        with tempfile.TemporaryDirectory() as tmp:
            merged, code, status = review_new_term(
                dictionary, Path(tmp) / "local.json", term, "reject"
            )
            self.assertEqual(status, "rejected")
            self.assertEqual(code, "")
            self.assertEqual(merged.entries, [])
            self.assertFalse((Path(tmp) / "local.json").exists())


if __name__ == "__main__":
    unittest.main()
