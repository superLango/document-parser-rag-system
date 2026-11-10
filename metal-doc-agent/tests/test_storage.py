import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from metal_doc_agent.storage import ArtifactStore


class AtomicWriteTests(unittest.TestCase):
    def test_retries_when_target_is_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp))
            real_replace = os.replace
            calls = {"count": 0}

            def flaky_replace(src: str, dst: str) -> None:
                calls["count"] += 1
                if calls["count"] < 3:
                    raise PermissionError("target locked")
                real_replace(src, dst)

            with mock.patch(
                "metal_doc_agent.storage.os.replace", side_effect=flaky_replace
            ):
                path = store.write_text("state.json", "ok")

            self.assertEqual(path.read_text(encoding="utf-8"), "ok")
            self.assertEqual(calls["count"], 3)


if __name__ == "__main__":
    unittest.main()
