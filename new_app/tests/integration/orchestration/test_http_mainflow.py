import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("HANSON_INTEGRATION") != "1",
    reason="requires postgres/minio; set HANSON_INTEGRATION=1",
)

# 集成链路使用 fake 阶段，避免依赖外部 OCR/沙箱服务。
os.environ.setdefault("OCR_USE_FAKE", "true")
os.environ.setdefault("ROUTE_USE_FAKE", "true")
os.environ.setdefault("SANDBOX_USE_FAKE", "true")
os.environ.setdefault("REVIEW_USE_FAKE", "true")
os.environ.setdefault("HUMAN_REVIEW_REQUIRED", "false")


def _client():
    from fastapi.testclient import TestClient

    from services.orchestration.main import app

    return TestClient(app)


def test_upload_create_run_idempotency_and_cancel() -> None:
    from services.orchestration.state import is_terminal

    body = f"Q355B tensile test {uuid.uuid4()}".encode()
    files = {"file": ("demo.txt", body, "text/plain")}

    with _client() as client:
        first = client.post("/internal/documents", files=files)
        assert first.status_code == 201
        document = first.json()

        repeat = client.post("/internal/documents", files=files)
        assert repeat.status_code == 201
        assert repeat.json()["id"] == document["id"]

        payload = {"recipe_channel": "stable"}
        run = client.post(
            f"/internal/documents/{document['id']}/runs", json=payload
        )
        assert run.status_code == 201
        run_id = run.json()["id"]

        duplicate = client.post(
            f"/internal/documents/{document['id']}/runs", json=payload
        )
        assert duplicate.json()["id"] == run_id

        events = client.get(f"/internal/runs/{run_id}/events").json()
        assert events[0]["type"] == "run.created"
        assert events[0]["payload"]["document_id"] == document["id"]

        cancel = client.post(f"/internal/runs/{run_id}/cancel")
        assert cancel.status_code in (200, 409)

        current = client.get(f"/internal/runs/{run_id}").json()
        assert current["id"] == run_id
        assert is_terminal(current["status"])

        timeline = client.get(f"/internal/runs/{run_id}/timeline")
        assert timeline.status_code == 200
        assert timeline.json()["run"]["id"] == run_id
