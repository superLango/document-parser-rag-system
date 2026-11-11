"""Sandbox smoke check executed inside the sandbox service container.

Usage:
    docker exec -i hanson-new-app-sandbox-1 python - < scripts/dev/sandbox-check.py
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request

import boto3
from botocore.client import Config

ENDPOINT = os.environ.get("OBJECT_STORAGE_ENDPOINT", "http://minio:9000")
BUCKET = os.environ.get("OBJECT_STORAGE_BUCKET", "hanson-docs")
ACCESS_KEY = os.environ.get("OBJECT_STORAGE_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("OBJECT_STORAGE_SECRET_KEY", "minioadmin")
BASE = os.environ.get("SANDBOX_BASE", "http://localhost:8004")

OCR = {
    "schema_version": "ocr/1",
    "tables": [
        {
            "table_id": "T1",
            "page_no": 1,
            "profile": "mechanical_properties",
            "n_cols": 4,
            "header_paths": [
                ["牌号"],
                ["规格"],
                ["抗拉强度 Rm/MPa"],
                ["断后伸长率 A/%"],
            ],
            "rows": [
                ["牌号", "规格", "抗拉强度 Rm/MPa", "断后伸长率 A/%"],
                ["Q355B", "≤16", "470", "22"],
                ["Q235B", "≤16", "400", "26"],
            ],
        }
    ],
}


def client():
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:  # noqa: BLE001
        s3.create_bucket(Bucket=BUCKET)
    return s3


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    print("runtime:", json.dumps(get_json(f"{BASE}/internal/sandbox/runtime"), ensure_ascii=False))

    s3 = client()
    data = json.dumps(OCR, ensure_ascii=False, sort_keys=True).encode("utf-8")
    key = "runs/sandbox-check/ocr.json"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="application/json")
    digest = hashlib.sha256(data).hexdigest()

    request = {
        "schema_version": "1.0",
        "trace_id": "sandbox-check",
        "run_id": "sandbox-check",
        "document": {
            "document_id": "sandbox-check",
            "filename": "sandbox-check.md",
            "storage_key": "documents/sandbox-check.md",
            "sha256": "0" * 64,
        },
        "ocr": {"storage_key": key, "sha256": digest},
        "assignments": [
            {
                "table_id": "T1",
                "recipe_id": "mechanical_properties_v1",
                "version": "1.0.0",
            }
        ],
        "recipe": {"recipe_id": "mechanical_properties_v1", "version": "1.0.0"},
        "template": {"template_id": "product_full", "version": "1.0.0"},
        "engine": {
            "api": "sandbox-engine/1",
            "version": "sandbox-engine/1",
            "image": os.environ.get("SANDBOX_ENGINE_IMAGE", "hanson-sandbox-runtime:local"),
        },
        "limits": {
            "cpu": 1.0,
            "memory_mb": 256,
            "pids": 64,
            "timeout_seconds": 60,
            "tmpfs_mb": 32,
        },
    }
    body = json.dumps(request, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(
        f"{BASE}/internal/sandbox/execute",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=300) as response:
        result = json.loads(response.read())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "succeeded":
        return 1
    for role, item in sorted(result.get("outputs", {}).items()):
        payload = s3.get_object(Bucket=BUCKET, Key=item["storage_key"])["Body"].read()
        ok = hashlib.sha256(payload).hexdigest() == item["sha256"]
        print(f"artifact {role}: {len(payload)} bytes sha_ok={ok}")
        if not ok:
            return 1
    records = json.loads(
        s3.get_object(
            Bucket=BUCKET, Key=result["outputs"]["records"]["storage_key"]
        )["Body"].read()
    )
    print("records:", json.dumps(records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
