from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    __import__("os").getenv("HANSON_INTEGRATION") != "1",
    reason="requires minio; set HANSON_INTEGRATION=1",
)


def test_parse_file_with_mock_backend() -> None:
    from services.ocr.main import app

    with TestClient(app) as client:
        response = client.post(
            "/internal/ocr/parse-file?backend=mock",
            files={"file": ("demo.txt", b"Q355B tensile 470 22", "text/plain")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["backend"] == "mock"
        assert body["pages"]


def test_empty_file_is_rejected() -> None:
    from services.ocr.main import app

    with TestClient(app) as client:
        response = client.post(
            "/internal/ocr/parse-file?backend=mock",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code == 400
