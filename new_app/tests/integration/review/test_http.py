from __future__ import annotations

from fastapi.testclient import TestClient


def test_rules_endpoint_lists_ruleset() -> None:
    from services.review.main import app

    with TestClient(app) as client:
        response = client.get("/internal/review/rules")
        assert response.status_code == 200
        body = response.json()
        assert body["ruleset_version"]
        assert "M5-ID-001" in body["rules"]


def test_empty_run_returns_report() -> None:
    from services.review.main import app

    with TestClient(app) as client:
        response = client.post(
            "/internal/review",
            json={"run_id": "run-empty", "records": [], "tables": []},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"pass", "warn", "fail"}
        assert isinstance(body["findings"], list)
        assert isinstance(body["stats"], dict)
