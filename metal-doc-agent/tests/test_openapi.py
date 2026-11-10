import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parents[2]
API_DIR = PROJECT / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
SPEC_PATH = PROJECT / "docs" / "openapi" / "standard-extraction.yaml"
LIVE_PATH = PROJECT / "packages" / "contracts" / "openapi.json"


class OpenApiDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8")) if SPEC_PATH.exists() else {}

    def test_spec_is_valid_and_covers_target_api(self) -> None:
        self.assertTrue(SPEC_PATH.exists(), "OpenAPI draft is missing")
        self.assertEqual(self.spec["openapi"], "3.1.0")
        paths = self.spec["paths"]
        for required in (
            "/v1/jobs",
            "/v1/jobs/{job_id}/items",
            "/v1/jobs/{job_id}/alignment",
            "/v1/business-dictionary",
            "/v1/documents",
            "/v1/documents/{document_id}/field-reviews",
            "/v1/documents/{document_id}/field-reviews/batch",
            "/v1/documents/{document_id}/field-diff",
            "/v1/documents/{document_id}/review-risks",
            "/v1/standard-extractions",
        ):
            self.assertIn(required, paths)
        for path, operations in paths.items():
            for method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                self.assertIn(method, {"get", "post", "put", "patch", "delete"})
                self.assertIn(
                    operation.get("x-status"),
                    {"implemented", "planned"},
                    f"{method.upper()} {path} missing x-status",
                )
                self.assertTrue(
                    operation.get("operationId"),
                    f"{method.upper()} {path} missing operationId",
                )

    def test_implemented_paths_exist_in_live_app(self) -> None:
        from fastapi.routing import APIRoute

        from hanson_api.config import PlatformSettings
        from hanson_api.router import create_platform_router
        from metal_doc_agent.api import create_app
        from metal_doc_agent.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                project_root=PROJECT / "metal-doc-agent",
                data_dir=root / "engine",
                ocr_backend="mock",
                extractor_backend="mock",
                glm_ocr_base_url=None,
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
            )
            platform_settings = PlatformSettings(
                data_dir=root / "platform",
                database_url=f"sqlite:///{(root / 'platform' / 'platform.db').as_posix()}",
                secret_key="test-secret",
                upload_dir=root / "uploads",
                engine_data_dir=root / "engine",
            )
            app = create_app(settings)
            router = create_platform_router(platform_settings, settings)
            app.include_router(router)
            live: set[tuple[str, str]] = set()

            def collect(routes) -> None:  # noqa: ANN001
                for route in routes:
                    if isinstance(route, APIRoute):
                        for method in route.methods:
                            live.add((route.path, method.lower()))
                        continue
                    included = getattr(route, "original_router", None)
                    if included is not None:
                        collect(included.routes)

            collect(app.routes)
            engine = getattr(router, "_platform_engine", None)
            if engine is not None:
                engine.dispose()

        implemented = {
            (path, method)
            for path, operations in self.spec["paths"].items()
            for method, operation in operations.items()
            if isinstance(operation, dict)
            and operation.get("x-status") == "implemented"
        }
        missing = sorted(implemented - live)
        self.assertEqual(missing, [], f"spec routes not implemented: {missing}")

    def test_exported_contract_is_platform_plane(self) -> None:
        self.assertTrue(LIVE_PATH.exists(), "run apps/api/tools/export_openapi.py")
        live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
        self.assertIn("/v1/auth/login", live["paths"])
        self.assertIn("/v1/documents", live["paths"])
        self.assertIn("/v1/business-dictionary", live["paths"])
        for path in (
            "/v1/documents/{document_id}/field-reviews",
            "/v1/documents/{document_id}/field-reviews/batch",
            "/v1/documents/{document_id}/field-diff",
            "/v1/documents/{document_id}/review-risks",
        ):
            self.assertIn(path, live["paths"])
        # R2 boundary: engine data routes must not be exported by the platform.
        self.assertNotIn("/v1/jobs", live["paths"])
        self.assertNotIn("/v1/batches", live["paths"])
        self.assertNotIn("/v1/recipes", live["paths"])


if __name__ == "__main__":
    unittest.main()
