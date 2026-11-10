import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.canonicalize import (
    DictionaryIndex,
    align_inventory,
    build_whitelist,
    diff_dictionaries,
    load_dictionary,
    load_dictionary_path,
    load_new_terms,
    match_item,
    match_method,
    match_method_cell,
    match_property,
    merge_dictionaries,
    promote_term,
    render_prompt,
    save_new_terms,
    write_dictionary_parts,
)
from metal_doc_agent.canonicalize.methods import method_year
from metal_doc_agent.canonicalize.normalize import (
    normalize_item_name,
    normalize_standard_no,
    standard_base,
)
from metal_doc_agent.canonicalize.terms import merge_new_terms
from metal_doc_agent.contracts import (
    BusinessDictionary,
    BusinessDictionaryEntry,
    ItemInventory,
    ItemInventoryEntry,
    NewTerm,
    NewTermStore,
)

ROOT = Path(__file__).resolve().parents[1]


def make_index() -> tuple[BusinessDictionary, DictionaryIndex]:
    dictionary = load_dictionary(ROOT, use_override=False)
    return dictionary, DictionaryIndex.build(dictionary)


def make_item(raw: str, family: str, facets: dict | None = None) -> ItemInventoryEntry:
    return ItemInventoryEntry(
        item_raw=raw,
        item_canonical=raw,
        item_family=family,
        facets=facets or {},
        evidence=["ev:test"],
    )


class NormalizeTests(unittest.TestCase):
    def test_item_and_standard_normalization(self) -> None:
        self.assertEqual(normalize_item_name(" 常温拉伸试验 "), "室温拉伸")
        self.assertEqual(normalize_item_name("ＨＢＷ"), "hbw")
        self.assertEqual(normalize_standard_no("GB/T 228.1—2010"), "GB/T228.1-2010")
        self.assertEqual(standard_base("GB/T 228.1-2010"), "GB/T228.1")


class ItemMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dictionary, cls.index = make_index()

    def test_exact(self) -> None:
        match = match_item(make_item("化学成分", "chemical_composition"), self.index)
        self.assertEqual(match.canonical_id, "ITEM_CHEMICAL")
        self.assertEqual(match.match_type, "exact")

    def test_alias_and_facets(self) -> None:
        match = match_item(
            make_item("常温拉伸", "tensile", {"temperature": "室温"}),
            self.index,
        )
        self.assertEqual(match.canonical_id, "ITEM_TENSILE_RT")
        self.assertEqual(match.status, "matched")

    def test_temperature_conflict(self) -> None:
        match = match_item(
            make_item("高温拉伸", "tensile", {"temperature": "高温"}),
            self.index,
        )
        self.assertEqual(match.canonical_id, "ITEM_TENSILE_HT")

    def test_hardness_scales(self) -> None:
        brinell = match_item(
            make_item("HBW", "hardness", {"hardness_scale": "brinell"}),
            self.index,
        )
        rockwell = match_item(
            make_item("洛氏硬度", "hardness", {"hardness_scale": "rockwell"}),
            self.index,
        )
        ambiguous = match_item(make_item("硬度", "hardness"), self.index)
        self.assertEqual(brinell.canonical_id, "ITEM_HARDNESS_BRINELL")
        self.assertEqual(rockwell.canonical_id, "ITEM_HARDNESS_ROCKWELL")
        self.assertEqual(ambiguous.status, "ambiguous")

    def test_new_unknown_family(self) -> None:
        match = match_item(make_item("发货检验", "unknown"), self.index)
        self.assertEqual(match.status, "new")
        self.assertEqual(match.dictionary_version, self.dictionary.version)

    def test_semantic_injection(self) -> None:
        match = match_item(
            make_item("摆锤试验", "impact"),
            self.index,
            semantic=lambda left, right: 0.95 if right == "夏比冲击" else 0.1,
        )
        self.assertEqual(match.match_type, "semantic")
        self.assertEqual(match.canonical_id, "ITEM_IMPACT_CHARPY")


class MethodMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dictionary, cls.index = make_index()

    def test_standard_edition(self) -> None:
        match = match_method("GB/T 228.1-2010", self.index)
        self.assertEqual(match.canonical_id, "M_GB228_1")
        self.assertEqual(match.match_type, "exact")

    def test_multi_standard_cell(self) -> None:
        matches = match_method_cell("GB/T 230.1、GB/T 231.1", self.index)
        self.assertEqual(
            sorted(match.canonical_id for match in matches),
            ["M_GB230_1", "M_GB231_1"],
        )

    def test_new_method(self) -> None:
        match = match_method("GB/T 99999", self.index)
        self.assertEqual(match.status, "new")
        self.assertEqual(match.dictionary_version, self.dictionary.version)


class AlignmentTests(unittest.TestCase):
    def test_align_inventory_sets_codes_and_new_terms(self) -> None:
        dictionary, index = make_index()
        inventory = ItemInventory(
            doc_id="doc",
            items=[
                make_item("HBW", "hardness", {"hardness_scale": "brinell"}),
                make_item("低温拉伸", "tensile", {"temperature": "低温"}),
                make_item("发货检验", "unknown"),
            ],
        )
        inventory.items[0].method_standard = "GB/T 231.1"
        aligned, result = align_inventory(inventory, index)
        self.assertEqual(aligned.items[0].business_code, "ITEM_HARDNESS_BRINELL")
        self.assertEqual(aligned.items[0].method_code, "M_GB231_1")
        self.assertIsNotNone(aligned.items[0].dictionary_version)
        self.assertEqual(aligned.items[2].match_type, "new")
        self.assertEqual(result.summary["items_matched"], 2)
        self.assertEqual(result.summary["items_new"], 1)
        self.assertTrue(any(term.raw == "发货检验" for term in result.new_terms))
        self.assertEqual(result.dictionary_version, dictionary.version)


class NewTermFlowTests(unittest.TestCase):
    def test_promote_and_reload(self) -> None:
        dictionary, index = make_index()
        with tempfile.TemporaryDirectory() as tmp:
            terms_path = Path(tmp) / "new_terms.json"
            override_path = Path(tmp) / "dictionary.local.json"
            store = NewTermStore(
                dictionary_version=dictionary.version,
                terms=[
                    NewTerm(
                        type="item",
                        raw="氨气腐蚀",
                        family="corrosion",
                        status="pending",
                        dictionary_version=dictionary.version,
                    )
                ],
            )
            save_new_terms(store, terms_path)
            loaded = load_new_terms(terms_path)
            promoted = promote_term(
                loaded,
                "氨气腐蚀",
                business_code="ITEM_AMMONIA",
                override_path=override_path,
                version=dictionary.version,
            )
            self.assertEqual(promoted.status, "active")
            save_new_terms(loaded, terms_path)
            self.assertEqual(load_new_terms(terms_path).terms[0].status, "active")

            override = BusinessDictionary.model_validate_json(
                override_path.read_text(encoding="utf-8")
            )
            merged = merge_dictionaries(dictionary, override)
            new_index = DictionaryIndex.build(merged)
            match = match_item(make_item("氨气腐蚀", "corrosion"), new_index)
            self.assertEqual(match.canonical_id, "ITEM_AMMONIA")

    def test_merge_dedupes_frequency(self) -> None:
        term = NewTerm(type="item", raw="氨气腐蚀", family="corrosion")
        store = NewTermStore(terms=[term])
        merged = merge_new_terms(store, [term])
        self.assertEqual(len(merged.terms), 1)
        self.assertEqual(merged.terms[0].frequency, 2)


class PromptAndDiffTests(unittest.TestCase):
    def test_whitelist_and_render(self) -> None:
        dictionary, index = make_index()
        whitelist = build_whitelist(index, ["hardness"])
        self.assertTrue(all(item["family"] == "hardness" for item in whitelist["items"]))
        rendered = render_prompt(
            "items:\n${whitelist_section}\nterms:${query_terms}\nfacets:${item_facets}",
            whitelist,
            query_terms=["HBW"],
            facets={"hardness_scale": "brinell"},
        )
        self.assertIn("ITEM_HARDNESS_BRINELL", rendered)
        self.assertIn("HBW", rendered)
        self.assertIn("hardness_scale=brinell", rendered)

    def test_dictionary_diff(self) -> None:
        dictionary, _ = make_index()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "override.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "next",
                        "entries": [
                            {
                                "business_code": "ITEM_NEW",
                                "business_name": "新项目",
                                "type": "item",
                                "family": "other",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            override = BusinessDictionary.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            diff = diff_dictionaries(dictionary, override)
            self.assertEqual(diff["old_version"], "master-20261027")
            self.assertEqual(diff["new_version"], "next")
            self.assertIn(("item", "ITEM_NEW"), diff["added"])


class CategoryDictionaryTests(unittest.TestCase):
    """Three term sets: 项目大类 (category), 检测项目 (item), 试验方法 (method)."""

    @classmethod
    def setUpClass(cls) -> None:
        dictionary = BusinessDictionary(
            version="cat-v1",
            source="offline_snapshot",
            entries=[
                {
                    "business_code": "CAT_TENSILE_RT",
                    "business_name": "室温拉伸",
                    "type": "category",
                    "family": "tensile",
                    "facets": {"temperature": ["室温"]},
                    "aliases": ["拉伸"],
                },
                {
                    "business_code": "CAT_LOW",
                    "business_name": "低倍",
                    "type": "category",
                    "family": "metallography",
                },
                {
                    "business_code": "CAT_CHEM",
                    "business_name": "化学成分",
                    "type": "category",
                    "family": "chemical_composition",
                },
                {
                    "business_code": "CAT_DIM",
                    "business_name": "尺寸",
                    "type": "category",
                    "family": "dimension",
                },
                {
                    "business_code": "CAT_SURFACE",
                    "business_name": "表面质量",
                    "type": "category",
                    "family": "surface",
                },
                {
                    "business_code": "CAT_PERSIST_HT",
                    "business_name": "高温光滑持久",
                    "type": "category",
                    "family": "stress_rupture",
                },
                {
                    "business_code": "CAT_HB",
                    "business_name": "布氏硬度",
                    "type": "category",
                    "family": "hardness",
                    "aliases": ["HBW"],
                },
                {
                    "business_code": "I_RM",
                    "business_name": "抗拉强度(Rm)",
                    "type": "item",
                    "family": "tensile",
                    "category_code": "CAT_TENSILE_RT",
                    "category_name": "室温拉伸",
                    "aliases": ["Rm"],
                },
                {
                    "business_code": "I_C",
                    "business_name": "C",
                    "type": "item",
                    "family": "chemical_composition",
                    "category_code": "CAT_CHEM",
                    "category_name": "化学成分",
                },
                {
                    "business_code": "M_229_2007",
                    "business_name": "金属夏比冲击试验",
                    "type": "method",
                    "standard_no": "GB/T 229-2007",
                },
                {
                    "business_code": "M_229_2020",
                    "business_name": "金属材料夏比摆锤冲击试验方法",
                    "type": "method",
                    "standard_no": "GB/T 229-2020",
                },
                {
                    "business_code": "M_228_99",
                    "business_name": "金属拉伸试验方法",
                    "type": "method",
                    "standard_no": "GB/T 228-99",
                },
                {
                    "business_code": "M_228_2010",
                    "business_name": "金属拉伸试验方法",
                    "type": "method",
                    "standard_no": "GB/T 228-2010",
                },
            ],
        )
        cls.index = DictionaryIndex.build(dictionary)

    def test_category_exact_and_containment(self) -> None:
        exact = match_item(make_item("室温拉伸", "tensile"), self.index)
        contained = match_item(make_item("低倍组织", "metallography"), self.index)
        missing = match_item(make_item("产品标识", "marking"), self.index)
        self.assertEqual(exact.canonical_id, "CAT_TENSILE_RT")
        self.assertEqual(exact.category_name, "室温拉伸")
        self.assertEqual(contained.canonical_id, "CAT_LOW")
        self.assertEqual(contained.match_type, "granularity")
        self.assertEqual(missing.status, "new")

    def test_checklist_rows_inherit_big_category(self) -> None:
        dimension = match_item(make_item("两端倒角", "unknown"), self.index)
        surface = match_item(make_item("划伤", "unknown"), self.index)
        self.assertEqual(dimension.category_name, "尺寸")
        self.assertEqual(surface.category_name, "表面质量")
        self.assertEqual(dimension.match_type, "granularity")

    def test_keyword_category_for_persistence_and_hardness(self) -> None:
        persistent = match_item(make_item("高温持久", "unknown"), self.index)
        hardness_item = make_item("硬度", "unknown")
        hardness_item.properties = ["HBW"]
        hardness = match_item(hardness_item, self.index)
        self.assertEqual(persistent.category_name, "高温光滑持久")
        self.assertEqual(hardness.category_name, "布氏硬度")

    def test_property_symbol_and_element(self) -> None:
        rm = match_property("Rm", self.index, category_code="CAT_TENSILE_RT")
        carbon = match_property("C", self.index, category_code="CAT_TENSILE_RT")
        self.assertEqual(rm.canonical_id, "I_RM")
        self.assertEqual(rm.status, "matched")
        self.assertEqual(carbon.canonical_id, "I_C")

    def test_method_edition(self) -> None:
        generic = match_method("GB/T 229", self.index)
        exact = match_method("GB/T 229-2007", self.index)
        self.assertEqual(generic.canonical_id, "M_229_2020")
        self.assertIn("最新版本", generic.reason or "")
        # Business rule: the latest dictionary edition wins even when the
        # document cites an older year.
        self.assertEqual(exact.canonical_id, "M_229_2020")
        self.assertIn("最新版本", exact.reason or "")

    def test_method_year_two_and_four_digits(self) -> None:
        generic = match_method("GB/T 228", self.index)
        by_name = match_method("金属拉伸试验方法", self.index)
        self.assertEqual(generic.canonical_id, "M_228_2010")
        self.assertEqual(by_name.canonical_id, "M_228_2010")
        self.assertEqual(method_year("GB/T 228-99"), 1999)
        self.assertEqual(method_year("GB/T 228-09"), 2009)
        self.assertEqual(method_year("GB/T 228-2010"), 2010)
        self.assertEqual(method_year("ISO 148-1:2016"), 2016)
        self.assertEqual(method_year(None), 0)

    def test_property_alias_outputs_dictionary_name(self) -> None:
        match = match_property("Rm", self.index, category_code="CAT_TENSILE_RT")
        self.assertEqual(match.canonical_name, "抗拉强度(Rm)")
        self.assertEqual(match.match_type, "alias")

    def test_strict_category_mode_excludes_unknown(self) -> None:
        inventory = ItemInventory(
            doc_id="strict-doc",
            items=[make_item("产品标识", "marking")],
        )
        advisory, advisory_result = align_inventory(
            inventory, self.index, category_mode="advisory"
        )
        strict, strict_result = align_inventory(
            inventory, self.index, category_mode="strict"
        )
        self.assertNotEqual(advisory.items[0].status, "not_applicable")
        self.assertEqual(strict.items[0].status, "not_applicable")
        self.assertEqual(strict_result.summary["categories_excluded"], 1)
        self.assertEqual(advisory_result.summary["categories_excluded"], 0)
        # 大类级别不产生新词候选：规则以词典为准。
        self.assertFalse(
            any(term.type == "category" for term in advisory_result.new_terms)
        )
        self.assertFalse(
            any(term.type == "category" for term in strict_result.new_terms)
        )


class SplitDictionaryTests(unittest.TestCase):
    def test_split_roundtrip_preserves_entries(self) -> None:
        dictionary = load_dictionary(ROOT, use_override=False)
        with tempfile.TemporaryDirectory() as tmp:
            write_dictionary_parts(tmp, dictionary)
            loaded = load_dictionary_path(tmp)
            self.assertEqual(loaded.version, dictionary.version)
            self.assertEqual(
                sorted((entry.type, entry.business_code) for entry in loaded.entries),
                sorted(
                    (entry.type, entry.business_code)
                    for entry in dictionary.entries
                ),
            )
            self.assertTrue((Path(tmp) / "categories.json").exists())
            self.assertTrue((Path(tmp) / "items.json").exists())
            self.assertTrue((Path(tmp) / "methods.json").exists())

    def test_split_loader_keeps_type_when_file_entry_lacks_it(self) -> None:
        dictionary = BusinessDictionary(
            version="split-v1",
            source="offline_snapshot",
            entries=[
                BusinessDictionaryEntry(
                    business_code="CAT:1",
                    business_name="低倍",
                    type="category",
                ),
                BusinessDictionaryEntry(
                    business_code="ITEM:1",
                    business_name="低倍组织",
                    type="item",
                    category_code="CAT:1",
                    category_name="低倍",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_dictionary_parts(tmp, dictionary)
            raw = json.loads(paths["item"].read_text(encoding="utf-8"))
            raw["entries"][0].pop("type", None)
            paths["item"].write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8"
            )
            loaded = load_dictionary_path(tmp)
            self.assertEqual(
                {entry.type for entry in loaded.entries}, {"category", "item"}
            )


if __name__ == "__main__":
    unittest.main()
