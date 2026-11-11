#!/usr/bin/env python3
"""M6 feedback -> triage -> repair -> candidate -> verify -> promote E2E."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

NEW_APP = Path(__file__).resolve().parents[2]
API = os.getenv("API_BASE", "http://localhost:18000")
REGISTRY = os.getenv("REGISTRY_BASE", "http://localhost:18005")
FIXTURE = NEW_APP / "tests" / "fixtures" / "mechanical-z.md"
OUT = Path(
    os.getenv("E2E_OUT", str(NEW_APP / "docs" / "reports" / "M6-feedback-e2e.json"))
)
TERMINAL = {"STRUCTURED_READY", "REVIEW_FAILED", "FAILED", "CANCELLED"}


def wait_run(client: httpx.Client, run_id: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{API}/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] in TERMINAL:
            return run
        time.sleep(1)
    raise TimeoutError(f"run {run_id} did not finish")


def create_run(client: httpx.Client, document_id: str) -> dict:
    response = client.post(
        f"{API}/v1/documents/{document_id}/runs",
        json={"recipe_channel": "stable", "parse_profile": "standard"},
    )
    response.raise_for_status()
    run = response.json()
    return wait_run(client, run["id"])


def result_of(client: httpx.Client, run_id: str) -> dict:
    response = client.get(f"{API}/v1/runs/{run_id}/result")
    response.raise_for_status()
    return response.json().get("result") or {}


def feedback_payload(
    run_id: str,
    *,
    measure: str = "Z",
    unit: str = "%",
    family: str = "tensile",
    description: str = "断面收缩率 Z 未抽取",
    expected_value: str = "22",
) -> dict:
    return {
        "run_id": run_id,
        "category": "missing_measure",
        "target": {
            "recipe_id": "mechanical_properties_v1",
            "measure": measure,
            "unit": unit,
            "family": family,
        },
        "description": description,
        "expected_value": expected_value,
        "reporter": "m6-e2e",
    }


def stable_version(client: httpx.Client) -> str:
    response = client.get(f"{REGISTRY}/internal/recipes/mechanical_properties_v1")
    response.raise_for_status()
    return str((response.json().get("channels") or {}).get("stable") or "")


def main() -> int:
    report: dict = {"steps": []}
    with httpx.Client(timeout=300) as client:
        health = client.get(f"{API}/v1/health")
        health.raise_for_status()

        with FIXTURE.open("rb") as handle:
            upload = client.post(
                f"{API}/v1/documents",
                files={"file": (FIXTURE.name, handle, "text/markdown")},
            )
        upload.raise_for_status()
        document = upload.json()
        before = create_run(client, document["id"])
        before_result = result_of(client, before["id"])
        before_version = (before_result.get("recipes") or [{}])[0].get("version", "")
        report["steps"].append(
            {
                "step": "before_run",
                "run_id": before["id"],
                "status": before["status"],
                "recipe_version": before_version,
            }
        )
        if before["status"] != "STRUCTURED_READY":
            report["error"] = "before run failed"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1

        created = client.post(f"{API}/v1/feedback", json=feedback_payload(before["id"]))
        created.raise_for_status()
        feedback = created.json()
        report["steps"].append(
            {
                "step": "feedback_created",
                "feedback_id": feedback["id"],
                "status": feedback["status"],
            }
        )

        processed = client.post(f"{API}/v1/feedback/{feedback['id']}/process")
        processed.raise_for_status()
        proposed = processed.json()
        report["steps"].append(
            {
                "step": "processed",
                "status": proposed["status"],
                "triage": proposed.get("triage"),
                "candidate": proposed.get("candidate"),
                "verification": proposed.get("verification"),
            }
        )
        if proposed["status"] != "verified":
            report["error"] = f"feedback processing ended at {proposed['status']}"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1
        verification = proposed.get("verification") or {}
        if not verification.get("passed"):
            report["error"] = "verification did not pass"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1
        candidate_version = (proposed.get("candidate") or {}).get("candidate_version")
        if not candidate_version:
            report["error"] = "candidate version missing"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1

        approved = client.post(
            f"{API}/v1/feedback/{feedback['id']}/verify",
            json={"decision": "approve", "reason": "M6 E2E approve", "actor": "operator"},
        )
        approved.raise_for_status()
        promoted = approved.json()
        report["steps"].append(
            {"step": "approved", "status": promoted["status"]}
        )
        if promoted["status"] != "promoted":
            report["error"] = "promotion failed"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1

        after = create_run(client, document["id"])
        after_result = result_of(client, after["id"])
        after_version = (after_result.get("recipes") or [{}])[0].get("version", "")
        report["steps"].append(
            {
                "step": "after_run",
                "run_id": after["id"],
                "status": after["status"],
                "recipe_version": after_version,
            }
        )
        if after_version != candidate_version:
            report["error"] = f"stable version {after_version} != {candidate_version}"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1

        # Reject path: Re stays unbound after the Z promotion, so a second
        # feedback must build another candidate and discard it on rejection.
        second = client.post(
            f"{API}/v1/feedback",
            json=feedback_payload(
                before["id"],
                measure="Re",
                unit="MPa",
                family="tensile",
                description="屈服强度 Re 未抽取（拒绝路径）",
                expected_value="345",
            ),
        )
        second.raise_for_status()
        second_feedback = second.json()
        processed_second = client.post(
            f"{API}/v1/feedback/{second_feedback['id']}/process"
        )
        processed_second.raise_for_status()
        second_body = processed_second.json()
        report["steps"].append(
            {"step": "reject_processed", "status": second_body["status"]}
        )
        if second_body["status"] == "verified":
            rejected = client.post(
                f"{API}/v1/feedback/{second_feedback['id']}/verify",
                json={
                    "decision": "reject",
                    "reason": "M6 E2E reject",
                    "actor": "operator",
                },
            )
            rejected.raise_for_status()
            report["steps"].append(
                {"step": "rejected", "status": rejected.json()["status"]}
            )
            if rejected.json()["status"] != "discarded":
                report["error"] = "reject did not discard"
                OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                return 1
            stable_after = stable_version(client)
            report["steps"].append(
                {"step": "stable_after_discard", "version": stable_after}
            )
            if stable_after != candidate_version:
                report["error"] = (
                    f"discard changed stable: {stable_after} != {candidate_version}"
                )
                OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                return 1
        else:
            report["error"] = f"second feedback ended at {second_body['status']}"
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 1

    report["status"] = "passed"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
