#!/usr/bin/env python3
"""Smoke-test the Qwen 35B NVFP4 endpoint through the model gateway."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from hanson_contracts import ModelMessage  # noqa: E402

from services.agent.model_gateway import (  # noqa: E402
    ModelEndpoint,
    ModelGateway,
    ModelGatewayConfig,
)


async def main() -> int:
    base_url = os.environ.get("AGENT_BASE_URL_TERTIARY", "http://192.168.1.35:9988")
    model = os.environ.get("AGENT_MODEL", "Qwen3.6-35B-A3B-NVFP4")
    gateway = ModelGateway(
        ModelGatewayConfig(
            model=model,
            endpoints=(ModelEndpoint(name="tertiary", base_url=base_url),),
            timeout_seconds=180,
            max_tokens=128,
            json_mode=True,
        )
    )
    try:
        messages = [
            ModelMessage(role="system", content="Return only one JSON value."),
            ModelMessage(
                role="user",
                content='Return {"ok": true, "role": "smoke"} and nothing else.',
            ),
        ]
        value, response = await gateway.chat_json(messages)
        print(
            json.dumps(
                {
                    "value": value,
                    "endpoint": response.endpoint,
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "latency_ms": response.latency_ms,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if value.get("ok") is True else 1
    finally:
        await gateway.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
