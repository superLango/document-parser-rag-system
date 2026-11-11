import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from metal_doc_agent.canonicalize import (
    BusinessApiError,
    DictionaryIndex,
    HttpDictionaryAdapter,
    match_item,
)
from metal_doc_agent.contracts import (
    BusinessDictionary,
    ItemInventory,
    ItemInventoryEntry,
)
from tools import business_smoke

TOKEN = "secret-token"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": "unauthorized"})
            return
        if self.path == "/api/items":
            self._send(
                200,
                {
                    "version": "live-v1",
                    "data": [
                        {
                            "item_code": "I-HBW",
                            "item_name": "HBW",
                            "family": "hardness",
                            "facets": {"hardness_scale": ["brinell"]},
                            "aliases": "布氏硬度、布氏硬度试验",
                            "enabled": 1,
                        },
                        {
                            "project_code": "I-CHEM",
                            "project_name": "化学成分",
                            "category": "chemical_composition",
                            "status": "启用",
                        },
                    ],
                },
            )
            return
        if self.path == "/api/methods":
            self._send(
                200,
                {
                    "version": "live-v1",
                    "data": [
                        {
                            "method_code": "M-231",
                            "method_name": "布氏硬度试验方法",
                            "std_no": "GB/T 231.1",
                        }
                    ],
                },
            )
            return
        if self.path == "/api/dictionary":
            self._send(
                200,
                {
                    "version": "live-v1",
                    "entries": [
                        {
                            "business_code": "I-HBW",
                            "business_name": "HBW",
                            "type": "item",
                            "family": "hardness",
                        }
                    ],
                },
            )
            return
        if self.path == "/api/broken":
            self._send(
                200,
                {"data": [{"item_name": "缺少编码"}]},
            )
            return
        self._send(404, {"error": "not found"})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Dictionary-Version", "live-v1")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return


class BusinessApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_split_endpoints_and_field_aliases(self) -> None:
        dictionary = HttpDictionaryAdapter(
            self.base_url,
            api_key=TOKEN,
            items_path="/api/items",
            methods_path="/api/methods",
        ).load()
        self.assertEqual(dictionary.version, "live-v1")
        self.assertEqual(len(dictionary.entries), 3)
        item = next(entry for entry in dictionary.entries if entry.type == "item")
        method = next(
            entry for entry in dictionary.entries if entry.type == "method"
        )
        self.assertEqual(item.facets, {"hardness_scale": ["brinell"]})
        self.assertEqual(item.aliases, ["布氏硬度", "布氏硬度试验"])
        self.assertEqual(item.status, "active")
        self.assertEqual(method.standard_no, "GB/T 231.1")

        index = DictionaryIndex.build(dictionary)
        match = match_item(
            ItemInventoryEntry(
                item_raw="HBW",
                item_family="hardness",
                facets={"hardness_scale": "brinell"},
            ),
            index,
        )
        self.assertEqual(match.canonical_id, "I-HBW")

    def test_single_dictionary_endpoint(self) -> None:
        dictionary = HttpDictionaryAdapter(
            self.base_url,
            api_key=TOKEN,
            dictionary_path="/api/dictionary",
        ).load()
        self.assertEqual(len(dictionary.entries), 1)
        self.assertEqual(dictionary.entries[0].business_code, "I-HBW")

    def test_auth_failure(self) -> None:
        adapter = HttpDictionaryAdapter(
            self.base_url,
            api_key="wrong",
            items_path="/api/items",
            methods_path="/api/methods",
        )
        with self.assertRaises(BusinessApiError):
            adapter.load()

    def test_entry_missing_code(self) -> None:
        adapter = HttpDictionaryAdapter(
            self.base_url,
            api_key=TOKEN,
            dictionary_path="/api/broken",
        )
        with self.assertRaises(BusinessApiError):
            adapter.load()

    def test_business_smoke_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            doc_dir = runs / "doc1"
            doc_dir.mkdir(parents=True)
            inventory = ItemInventory(
                doc_id="doc1",
                items=[
                    ItemInventoryEntry(
                        item_raw="HBW",
                        item_family="hardness",
                        facets={"hardness_scale": "brinell"},
                        method_standard="GB/T 231.1",
                    ),
                    ItemInventoryEntry(
                        item_raw="化学成分",
                        item_family="chemical_composition",
                    ),
                ],
            )
            (doc_dir / "item_inventory.json").write_text(
                json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            out = Path(tmp) / "out"
            code = business_smoke.main(
                [
                    "--base-url",
                    self.base_url,
                    "--api-key",
                    TOKEN,
                    "--items-path",
                    "/api/items",
                    "--methods-path",
                    "/api/methods",
                    "--runs",
                    str(runs),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            report = json.loads(
                (out / "g1_8_live.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["alignment"]["items_matched"], 2)
            self.assertEqual(report["alignment"]["methods_matched"], 1)

    def test_business_smoke_snapshot(self) -> None:
        dictionary = BusinessDictionary(
            version="snapshot-v1",
            source="offline_snapshot",
            entries=[
                {
                    "business_code": "I-CHEM",
                    "business_name": "化学成分",
                    "type": "item",
                    "family": "chemical_composition",
                },
                {
                    "business_code": "M-231",
                    "business_name": "布氏硬度试验方法",
                    "type": "method",
                    "standard_no": "GB/T 231.1",
                },
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "dictionary.json"
            snapshot.write_text(
                json.dumps(dictionary.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            runs = Path(tmp) / "runs"
            doc_dir = runs / "doc1"
            doc_dir.mkdir(parents=True)
            inventory = ItemInventory(
                doc_id="doc1",
                items=[
                    ItemInventoryEntry(
                        item_raw="化学成分",
                        item_family="chemical_composition",
                        method_standard="GB/T 231.1",
                    )
                ],
            )
            (doc_dir / "item_inventory.json").write_text(
                json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            out = Path(tmp) / "out"
            code = business_smoke.main(
                [
                    "--snapshot",
                    str(snapshot),
                    "--runs",
                    str(runs),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
