"""Stage F tests: standalone API, zero-impact flag, worker."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.settings import Settings
from metal_doc_agent.selfheal.api import create_selfheal_app
from metal_doc_agent.selfheal.config import SelfHealSettings
from metal_doc_agent.selfheal.contracts import (
    FeedbackTarget,
    Finding,
    FindingSource,
    FindingVerdict,
)
from metal_doc_agent.selfheal.l2 import L2Repairer
from metal_doc_agent.selfheal.storage import SelfHealStore
from metal_doc_agent.selfheal.worker import run_once

AGENT_ROOT = Path(__file__).resolve().parents[1]
MD = """# Page 1

# 测试标准

## Table

<table border="1">
<tr><td rowspan="2">牌号</td><td colspan="2">力学性能(不小于)</td></tr>
<tr><td>抗拉强度Rm/MPa</td><td>断后伸长率A/%</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
<tr><td>2A15</td><td>400</td><td>8</td></tr>
</table>
"""


@pytest.fixture()
def job(tmp_path: Path) -> Path:
    md = tmp_path / "doc.md"
    md.write_text(MD, encoding="utf-8")
    out = tmp_path / "data" / "jobs" / "job-1"
    settings = dataclasses.replace(
        Settings.from_env(),
        project_root=AGENT_ROOT,
        data_dir=tmp_path / "data",
        ocr_backend="mock",
        extractor_backend="mock",
    )
    run_pipeline(md, out, settings=settings, coverage_template="product_full")
    return out


def _settings(tmp_path: Path, enabled: bool) -> SelfHealSettings:
    return dataclasses.replace(
        SelfHealSettings.from_env(project_root=AGENT_ROOT),
        enabled=enabled,
        root=tmp_path / "selfheal",
        db_path=tmp_path / "selfheal" / "selfheal.db",
        data_dir=tmp_path / "data",
    )


def _payload(job: Path) -> dict:
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    record = result["records"][0]
    return {
        "doc_id": result["document"]["doc_id"],
        "job_id": "job-1",
        "category": "wrong_value",
        "target": {
            "record_id": record["record_id"],
            "property": "Rm",
            "table_id": "T1",
        },
        "description": "抗拉强度应为 440",
        "expected_value": "440",
    }


def test_flag_off_registers_only_healthz(tmp_path):
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path, enabled=False)
    client = TestClient(create_selfheal_app(settings))
    assert client.get("/healthz").json()["enabled"] is False
    assert client.get("/v1/selfheal/feedback").status_code == 404
    assert client.post("/v1/selfheal/audit", json={"job_dir": "x"}).status_code == 404
    assert {route.path for route in client.app.routes} == {"/healthz"}
    assert not settings.db_path.exists()
    assert not settings.root.exists()


def test_flag_on_feedback_flow(tmp_path, job):
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path, enabled=True)
    client = TestClient(create_selfheal_app(settings))

    created = client.post("/v1/selfheal/feedback", json=_payload(job))
    assert created.status_code == 200
    body = created.json()
    assert body["problems"] == []
    feedback_id = body["feedback"]["feedback_id"]

    listed = client.get("/v1/selfheal/feedback").json()["items"]
    assert [item["feedback_id"] for item in listed] == [feedback_id]

    detail = client.get(f"/v1/selfheal/feedback/{feedback_id}").json()
    assert detail["findings"]

    message = client.post(
        f"/v1/selfheal/feedback/{feedback_id}/messages",
        json={"content": "补充：应为 440"},
    )
    assert message.status_code == 200

    processed = client.post(f"/v1/selfheal/feedback/{feedback_id}/process")
    assert processed.status_code == 200
    assert processed.json()["status"] in {
        "fixed",
        "needs_more_info",
        "processing",
        "unresolved",
    }

    metrics = client.get("/v1/selfheal/metrics").json()
    assert "feedback" in metrics

    ui = client.get("/selfheal/ui")
    assert ui.status_code == 200
    assert "Self-Heal" in ui.text


def test_proposal_rollback_endpoint(tmp_path, job):
    from fastapi.testclient import TestClient

    settings = _settings(tmp_path, enabled=True)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    record = result["records"][0]
    finding = Finding(
        doc_id=result["document"]["doc_id"],
        job_id="job-1",
        source=FindingSource.user,
        verdict=FindingVerdict.wrong,
        target=FeedbackTarget(record_id=record["record_id"], property="Rm", table_id="T1"),
        expected="440",
    )
    proposal, candidate = L2Repairer(settings).propose(
        finding, job, "column_alias.add", {"alias": "测试别名", "property": "Rm"}
    )
    store.add_proposal(proposal)
    store.add_candidate(candidate)
    overlay = Path(proposal.artifact_dir)
    assert overlay.exists()

    client = TestClient(create_selfheal_app(settings))
    response = client.post(f"/v1/selfheal/proposals/{proposal.proposal_id}/rollback")
    assert response.status_code == 200
    assert response.json()["status"] == "rolled_back"
    assert store.get_proposal(proposal.proposal_id).status.value == "rolled_back"
    assert not overlay.exists()


def test_worker_processes_open_feedback(tmp_path, job):
    settings = _settings(tmp_path, enabled=True)
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    from metal_doc_agent.selfheal.feedback import FeedbackService
    from metal_doc_agent.selfheal.contracts import FeedbackCreate

    service = FeedbackService(store, settings)
    service.create(FeedbackCreate.model_validate(_payload(job)))
    processed = run_once(settings)
    assert processed == 1
    assert store.list_feedback()[0].status.value != "open"
