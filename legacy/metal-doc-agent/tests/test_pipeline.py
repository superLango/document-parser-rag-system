import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.ingest import split_pages
from metal_doc_agent.pipeline import run_pipeline


SAMPLE = """# Page 1

## 4.5 室温力学性能

表1 力学性能

<table border="1">
  <tr><td rowspan="2">牌号</td><td colspan="3">室温力学性能</td></tr>
  <tr><td>Rm/MPa</td><td>Rp0.2/MPa</td><td>A/%</td></tr>
  <tr><td>2A14</td><td>430</td><td>350</td><td>10</td></tr>
</table>
"""


class PageSplitTests(unittest.TestCase):
    def test_html_comment_page_markers(self) -> None:
        text = "<!-- page: 1 -->\n# 标题\n<!-- page: 2 -->\n表格\n<!-- page: 3 -->\n结尾"
        pages = split_pages(text)
        self.assertEqual([page.page_no for page in pages], [1, 2, 3])
        self.assertEqual(pages[1].markdown, "表格")


class PipelineTests(unittest.TestCase):
    def test_mock_pipeline_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text(SAMPLE, encoding="utf-8")
            out = root / "out"
            result = run_pipeline(doc, out)

            self.assertTrue((out / "result.json").exists())
            self.assertTrue((out / "evidence.jsonl").exists())
            self.assertTrue((out / "audit.md").exists())
            self.assertTrue((out / "tablegrid" / "T1.json").exists())
            self.assertTrue((out / "item_inventory.json").exists())
            self.assertTrue((out / "links.json").exists())
            self.assertTrue((out / "coverage_audit.json").exists())
            self.assertIsNotNone(result.inventory)
            self.assertIsNotNone(result.alignment)
            self.assertTrue(
                result.alignment.dictionary_version.startswith("hanson-")
            )
            self.assertTrue((out / "alignment.json").exists())
            self.assertTrue((out / "new_terms.json").exists())

            payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")
            self.assertEqual(len(payload["records"]), 1)
            self.assertEqual(payload["records"][0]["grade"], "2A14")
            self.assertEqual(payload["records"][0]["properties"]["Rm"]["value"], 430)

            evidence = [
                json.loads(line)
                for line in (out / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(evidence), 3)
            self.assertEqual(evidence[0]["page_no"], 1)
            self.assertEqual(evidence[0]["table_id"], "T1")
            self.assertEqual(result.result.quality.status, "review")


if __name__ == "__main__":
    unittest.main()
