import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import CrossStandardTask, DocumentMeta, Page
from metal_doc_agent.cross_standard import detect_tasks
from metal_doc_agent.cross_standard_expand import expand_tasks
from metal_doc_agent.standards import StandardRecord, StandardRegistry


def doc() -> DocumentMeta:
    return DocumentMeta(doc_id="test-doc", source_path="x.md", file_name="x.md")


def write_catalog(test: unittest.TestCase, records: list[dict]) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "catalog.json"
    path.write_text(
        json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
    )
    return path


class CrossStandardTests(unittest.TestCase):
    def test_missing_parameter_creates_task(self) -> None:
        pages = [
            Page(
                page_no=18,
                markdown=(
                    "## 3.6 弯曲性能\n"
                    "要求弯曲性能的板、带材，按GB/T3880.2规定的弯曲半径进行弯曲试验后，"
                    "表面不应出现目视可见的裂纹。\n"
                ),
            )
        ]
        tasks = detect_tasks(pages, doc())
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task.inspection_item, "弯曲性能")
        self.assertEqual(task.missing_fields, ["弯曲半径"])
        self.assertEqual(task.requirement_standard, "GB/T 3880.2")
        self.assertEqual(task.status, "not_found")
        self.assertIn("未入库", task.gap or "")

    def test_method_only_reference_creates_no_task(self) -> None:
        pages = [
            Page(
                page_no=1,
                markdown=(
                    "## 4.5 拉伸试验\n"
                    "拉伸试验应按 GB/T 228.1 的规定进行。\n"
                    "## 4.6 硬度\n"
                    "按 GB/T 231.1 规定的方法对锻件进行布氏硬度检验。\n"
                ),
            )
        ]
        self.assertEqual(detect_tasks(pages, doc()), [])

    def test_registered_requirement_standard_resolves(self) -> None:
        pages = [
            Page(
                page_no=18,
                markdown=(
                    "## 3.6 弯曲性能\n"
                    "按GB/T3880.2规定的弯曲半径进行弯曲试验。\n"
                ),
            )
        ]
        registry = StandardRegistry(
            records=[
                StandardRecord(
                    standard_no="GB/T 3880.2",
                    edition="2012",
                    title="一般工业用铝及铝合金板、带材 第2部分：力学性能",
                    status="current",
                    doc_id="gbt3880_2_2012",
                )
            ]
        )
        task = detect_tasks(pages, doc(), registry=registry)[0]
        self.assertEqual(task.status, "resolved")
        self.assertEqual(task.resolved_doc_id, "gbt3880_2_2012")
        self.assertIsNone(task.gap)

    def test_registered_without_local_source_needs_source(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown="按 Q/S10-0537-2004 规定的测试项目进行检验。\n",
            )
        ]
        registry = StandardRegistry(
            records=[
                StandardRecord(
                    standard_no="Q/S 10-0537",
                    edition="2004",
                    title="TA15钛合金环形锻件",
                    status="current",
                )
            ]
        )
        task = detect_tasks(pages, doc(), registry=registry)[0]
        self.assertEqual(task.requirement_standard, "Q/S 10-0537")
        self.assertEqual(task.requirement_edition, "2004")
        self.assertEqual(task.status, "needs_source")
        self.assertEqual(task.resolution_basis, "dated")
        self.assertIn("无本地正文", task.gap or "")

    def test_registered_with_source_file_resolves(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown="按 Q/S10-0537-2004 规定的测试项目进行检验。\n",
            )
        ]
        registry = StandardRegistry(
            records=[
                StandardRecord(
                    standard_no="Q/S 10-0537",
                    edition="2004",
                    status="current",
                    doc_id="qs10_0537_2004",
                    source_file="markdown/x.md",
                )
            ]
        )
        task = detect_tasks(pages, doc(), registry=registry)[0]
        self.assertEqual(task.status, "resolved")
        self.assertEqual(task.resolved_doc_id, "qs10_0537_2004")

    def test_registered_record_uses_corpus_body_for_expansion(self) -> None:
        pages = [
            Page(page_no=4, markdown="按 Q/S10-0537-2004 规定的测试项目进行检验。\n")
        ]
        registry = StandardRegistry(
            records=[
                StandardRecord(
                    standard_no="Q/S 10-0537",
                    edition="2004",
                    status="current",
                    doc_id="qs10_0537_2004",
                )
            ]
        )
        catalog = write_catalog(
            self,
            [
                {
                    "file": "markdown/qs10_0537.md",
                    "standard_no": "Q/S 10-0537",
                    "edition": "2004",
                    "title": "TA15钛合金环形锻件",
                    "doc_type": "enterprise_standard",
                    "duplicate_of": None,
                    "cited_standards": [],
                }
            ],
        )
        task = detect_tasks(
            pages, doc(), registry=registry, catalog_path=catalog
        )[0]
        self.assertEqual(task.status, "resolved")
        self.assertEqual(task.resolved_doc_id, "qs10_0537_2004")
        self.assertEqual(task.resolved_source_file, "markdown/qs10_0537.md")

    def test_corpus_body_resolves_without_registry(self) -> None:
        pages = [
            Page(page_no=4, markdown="按 Q/S10-0537-2004 规定的测试项目进行检验。\n")
        ]
        catalog = write_catalog(
            self,
            [
                {
                    "file": "markdown/qs10_0537.md",
                    "standard_no": "Q/S 10-0537",
                    "edition": "2004",
                    "title": "TA15钛合金环形锻件",
                    "doc_type": "enterprise_standard",
                    "duplicate_of": None,
                    "cited_standards": [],
                }
            ],
        )
        task = detect_tasks(pages, doc(), catalog_path=catalog)[0]
        self.assertEqual(task.status, "resolved")
        self.assertEqual(task.resolved_source_file, "markdown/qs10_0537.md")
        self.assertEqual(task.resolution_basis, "corpus-body")

    def test_corpus_mention_only_reports_needs_source_hint(self) -> None:
        pages = [
            Page(page_no=4, markdown="按 Q/S10-0533-2004 规定的测试项目进行检验。\n")
        ]
        catalog = write_catalog(
            self,
            [
                {
                    "file": "markdown/agreement.md",
                    "standard_no": None,
                    "edition": None,
                    "title": "订货技术协议",
                    "doc_type": "technical_condition",
                    "duplicate_of": None,
                    "cited_standards": ["Q/S10-0533-2004"],
                }
            ],
        )
        registry = StandardRegistry(
            records=[
                StandardRecord(
                    standard_no="Q/S 10-0533",
                    edition="2004",
                    status="current",
                )
            ]
        )
        task = detect_tasks(
            pages, doc(), registry=registry, catalog_path=catalog
        )[0]
        self.assertEqual(task.status, "needs_source")
        self.assertIn("1 份文件引用该标准", task.gap or "")


class CrossStandardPatternTests(unittest.TestCase):
    """P4: phrase variants must not turn method references into tasks."""

    def test_std_first_allows_space_between_org_and_number(self) -> None:
        pages = [
            Page(
                page_no=2,
                markdown=(
                    "要求弯曲性能的板、带材，按 GB/T 3880.2 规定的弯曲半径"
                    "进行弯曲试验后，表面不应出现裂纹。\n"
                ),
            )
        ]
        task = detect_tasks(pages, doc())[0]
        self.assertEqual(task.requirement_standard, "GB/T 3880.2")
        self.assertEqual(task.missing_fields, ["弯曲半径"])

    def test_field_first_comply_extracts_parameter(self) -> None:
        pages = [
            Page(
                page_no=3,
                markdown="3.2.2 锻件成品化学成分允许偏差应符合 GB/T 222 的规定。\n",
            )
        ]
        task = detect_tasks(pages, doc())[0]
        self.assertEqual(task.requirement_standard, "GB/T 222")
        self.assertEqual(task.missing_fields, ["化学成分允许偏差"])
        self.assertEqual(task.inspection_item, "化学成分")

    def test_field_first_apply_extracts_parameter(self) -> None:
        pages = [
            Page(
                page_no=4,
                markdown=(
                    "30Si2MnCrMoVE和31Si2MnCrMoVE低倍缺陷应按 GJB 9443 进行检验。\n"
                ),
            )
        ]
        task = detect_tasks(pages, doc())[0]
        self.assertEqual(task.requirement_standard, "GJB 9443")
        self.assertEqual(task.missing_fields, ["低倍缺陷"])

    def test_std_first_without_verb_needs_parameter_noun(self) -> None:
        pages = [
            Page(
                page_no=6,
                markdown=(
                    "按 GB/T 3880.2 规定的弯曲半径。\n"
                    "按 GB/T 3880.2 规定的进行。\n"
                ),
            )
        ]
        tasks = detect_tasks(pages, doc())
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].missing_fields, ["弯曲半径"])

    def test_field_first_without_verb_creates_task(self) -> None:
        pages = [
            Page(
                page_no=13,
                markdown=(
                    "4 根据需方要求,并在合同中注明,要求钢板厚度方向性能时,"
                    "钢材厚度方向的断面收缩率应按 GB/T 5313 的规定。\n"
                ),
            )
        ]
        task = detect_tasks(pages, doc())[0]
        self.assertEqual(task.requirement_standard, "GB/T 5313")
        self.assertEqual(task.missing_fields, ["断面收缩率"])

    def test_optional_surface_quality_with_execute_creates_task(self) -> None:
        pages = [
            Page(
                page_no=18,
                markdown=(
                    "经供需双方协商,钢板的表面质量也可符合 GB/T 14977 的规定。\n"
                    "经供需双方协商,型钢的表面质量也可执行 YB/T 4427 的规定。\n"
                ),
            )
        ]
        tasks = detect_tasks(pages, doc())
        self.assertEqual([task.missing_fields[0] for task in tasks], ["表面质量", "表面质量"])
        self.assertEqual(
            [task.requirement_standard for task in tasks],
            ["GB/T 14977", "YB/T 4427"],
        )

    def test_method_and_subject_references_create_no_task(self) -> None:
        pages = [
            Page(
                page_no=5,
                markdown=(
                    "低倍试样制备按 GB/T 226 的规定进行。\n"
                    "超声检测按 GJB 1580A-2004 的规定进行。\n"
                    "检测结果应符合 GJB 1580A-2004 中 A 级的规定。\n"
                    "钢材的包装、标志和质量证明书应符合 GB/T 2101 的规定。\n"
                    "其测定方法按 ASTM E 208 的规定执行。\n"
                    "4.1.3 “Al”含量按GB/T 3190规定的方法计算。\n"
                ),
            )
        ]
        self.assertEqual(detect_tasks(pages, doc()), [])


class CrossStandardExpansionTests(unittest.TestCase):
    def test_expands_clause_value_and_writes_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "markdown"
            corpus.mkdir()
            (corpus / "ref.md").write_text(
                "<!-- page: 1 -->\n"
                "## 5.3 弯曲性能\n"
                "弯曲半径按 1.5 mm 执行。\n",
                encoding="utf-8",
            )
            job = root / "job"
            job.mkdir()
            task = CrossStandardTask(
                task_id="xstd-test",
                doc_id="doc-1",
                inspection_item="弯曲性能",
                missing_fields=["弯曲半径"],
                requirement_standard="GB/T 3880.2",
                requirement_edition="2012",
                status="resolved",
                resolved_source_file="markdown/ref.md",
            )
            summary = expand_tasks(job, root / "metal-doc-agent", [task])

            self.assertEqual(summary["expanded"], 1)
            self.assertEqual(task.expansion["extracted"][0]["value"], "1.5")
            self.assertEqual(task.expansion["extracted"][0]["unit"], "mm")
            self.assertTrue(task.provenance)
            merge = json.loads(
                (job / "cross_standard_merge.json").read_text(encoding="utf-8")
            )
            self.assertEqual(merge[0]["requirement"], "1.5mm")
            self.assertEqual(merge[0]["inspection_item"], "弯曲性能")

    def test_table_number_is_not_used_as_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "markdown"
            corpus.mkdir()
            (corpus / "ref.md").write_text(
                "<!-- page: 1 -->\n"
                "## 4.2.2 质量一致性检验\n"
                "取样数量以及相应要求和检验方法的章条号应符合表 4 的规定。\n",
                encoding="utf-8",
            )
            job = root / "job"
            job.mkdir()
            task = CrossStandardTask(
                task_id="xstd-table",
                doc_id="doc-1",
                inspection_item="质量一致性检验",
                missing_fields=["取样数量"],
                requirement_standard="Q/S 10-0537",
                status="resolved",
                resolved_source_file="markdown/ref.md",
            )
            expand_tasks(job, root / "metal-doc-agent", [task])
            self.assertIsNone(task.expansion)
            self.assertTrue(task.error)
            self.assertEqual(
                json.loads((job / "cross_standard_merge.json").read_text(encoding="utf-8")),
                [],
            )

    def test_missing_reference_file_becomes_needs_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "job"
            job.mkdir()
            task = CrossStandardTask(
                task_id="xstd-missing",
                doc_id="doc-1",
                inspection_item="弯曲性能",
                missing_fields=["弯曲半径"],
                requirement_standard="GB/T 3880.2",
                status="resolved",
                resolved_source_file="markdown/not-there.md",
            )
            expand_tasks(job, root / "metal-doc-agent", [task])
            self.assertEqual(task.status, "needs_source")
            self.assertIsNone(task.expansion)


if __name__ == "__main__":
    unittest.main()
