from fastapi.testclient import TestClient

from services.agent.main import app as agent_app
from services.api_gateway.main import app as gateway_app
from services.ocr.main import app as ocr_app
from services.orchestration.main import app as orchestration_app
from services.recipe_registry.main import app as recipe_app
from services.review.main import app as review_app
from services.sandbox.main import app as sandbox_app

SERVICES = [
    ("api-gateway", gateway_app),
    ("orchestration", orchestration_app),
    ("ocr", ocr_app),
    ("agent", agent_app),
    ("sandbox", sandbox_app),
    ("recipe-registry", recipe_app),
    ("review", review_app),
]


def test_services_health() -> None:
    for name, app in SERVICES:
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["service"] == name
