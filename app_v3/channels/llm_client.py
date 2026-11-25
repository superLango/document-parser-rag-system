"""app_v3 的轻量 LLM 客户端（OpenAI-compatible /chat/completions）。

默认走 DSH 代理（192.168.1.35:9989），代理会注入 enable_thinking=false。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = os.environ.get("V3_LLM_BASE_URL", "http://192.168.1.35:9989/v1")
DEFAULT_MODEL = os.environ.get("V3_LLM_MODEL", "Qwen3.6-35B-A3B-NVFP4")


class LlmError(RuntimeError):
    pass


def chat(prompt: str, *, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
         max_tokens: int = 4096, timeout: float = 120.0, retries: int = 2) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = ""
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-local"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body["choices"][0]["message"]["content"])
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise LlmError(last_error)
