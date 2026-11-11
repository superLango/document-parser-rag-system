"""M5 service health check, run inside a Compose service container."""

from __future__ import annotations

import json
import urllib.request

ENDPOINTS = [
    ("agent", "http://agent:8003/healthz"),
    ("agent-health", "http://agent:8003/internal/agent/health"),
    ("review", "http://review:8006/healthz"),
    ("review-rules", "http://review:8006/internal/review/rules"),
    ("orchestration", "http://orchestration:8001/healthz"),
]

for name, url in ENDPOINTS:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
        print(f"OK   {name}: {body[:800]}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name}: {exc}")
