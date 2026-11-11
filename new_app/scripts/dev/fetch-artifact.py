"""Fetch an object-store artifact for debugging.

Usage:
    docker exec -i hanson-new-app-sandbox-1 python - runs/<run>/records.json \
        < scripts/dev/fetch-artifact.py
"""

from __future__ import annotations

import json
import os
import sys

import boto3
from botocore.client import Config

key = sys.argv[1]
client = boto3.client(
    "s3",
    endpoint_url=os.environ.get("OBJECT_STORAGE_ENDPOINT", "http://minio:9000"),
    aws_access_key_id=os.environ.get("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
    aws_secret_access_key=os.environ.get("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
    region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"}),
)
body = client.get_object(
    Bucket=os.environ.get("OBJECT_STORAGE_BUCKET", "hanson-docs"), Key=key
)["Body"].read()
try:
    print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
except ValueError:
    print(body.decode("utf-8", "replace"))
