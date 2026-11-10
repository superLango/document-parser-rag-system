import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.pipeline import run_pipeline


REAL_DOC = Path(__file__).resolve().parents[2] / "标准文件" / "Q-Du 302-2015.md"


@unittest.skipUnless(REAL_DOC.exists(), "real Q-Du 302 corpus file is not present")
class RealCorpusTests(unittest.TestCase):
    def test_qdu302_mechanical_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(REAL_DOC, Path(tmp))
            self.assertGreaterEqual(len(result.result.tables), 5)
            self.assertGreaterEqual(len(result.result.records), 3)
            self.assertGreaterEqual(len(result.evidence), 3)
            mechanical = [
                table for table in result.result.tables if table.profile == "mechanical_properties"
            ]
            self.assertGreaterEqual(len(mechanical), 1)
            grades = {record.grade for record in result.result.records}
            self.assertIn("2A14", grades)


if __name__ == "__main__":
    unittest.main()
