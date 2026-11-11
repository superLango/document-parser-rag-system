"""M5 closure: backup drill and pilot acceptance pack."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class BackupDrillTests(unittest.TestCase):
    def test_local_drill_passes(self) -> None:
        drill = _load("backup_drill", "infra/backup/drill.py")
        with tempfile.TemporaryDirectory() as tmp:
            code = drill.main(
                ["--out", str(Path(tmp) / "drill.json"), "--md", str(Path(tmp) / "drill.md")]
            )
            self.assertEqual(code, 0)
            report = json.loads((Path(tmp) / "drill.json").read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(report["mode"], "local-sqlite+volume+fernet")
            self.assertTrue(report["checks"]["checksums_match"])
            self.assertTrue(report["checks"]["tamper_detected"])


class PilotPackTests(unittest.TestCase):
    def test_pack_lists_blockers_and_never_claims_pass(self) -> None:
        pack = _load("pilot_pack", "metal-doc-agent/tools/pilot_pack.py")
        with tempfile.TemporaryDirectory() as tmp:
            code = pack.main(
                [
                    "--eval",
                    str(ROOT / "metal-doc-agent" / "eval"),
                    "--out",
                    str(Path(tmp) / "pack.json"),
                    "--md",
                    str(Path(tmp) / "pack.md"),
                ]
            )
            self.assertEqual(code, 0)
            report = json.loads((Path(tmp) / "pack.json").read_text(encoding="utf-8"))
            self.assertFalse(report["g5_passed"])
            self.assertIn("试点部门验收", report["blockers"])
            self.assertIn("生产 SLA 99.5%", report["blockers"])
            self.assertEqual([row["decision"] for row in report["signoff"]], ["pending"] * 4)


if __name__ == "__main__":
    unittest.main()
