#!/usr/bin/env python3
"""Window benchmark for the Qwen 35B endpoint (32K/64K/128K prompts)."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

BASE_TEXT = (
    "材料牌号与力学性能要求如下：抗拉强度 Rm 不低于 470 MPa，"
    "屈服强度 Rp0.2 不低于 355 MPa，断后伸长率 A 不低于 22%，"
    "冲击吸收能量 KU2 不低于 27 J。试样应在室温下进行试验，"
    "试验方法按 GB/T 228.1 执行，取样方向为纵向。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen window benchmark")
    parser.add_argument("--base-url", default="http://192.168.1.35:9988")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-NVFP4")
    parser.add_argument("--sizes", default="32000,64000,120000")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--ssh-host", default="192.168.1.35")
    parser.add_argument("--ssh-user", default="grainuser")
    parser.add_argument(
        "--out",
        default="docs/reports/M5-window-benchmark.json",
    )
    return parser.parse_args()


def api_base(url: str) -> str:
    value = url.strip().rstrip("/")
    return value if value.endswith("/v1") else f"{value}/v1"


def count_tokens(client: httpx.Client, base: str, model: str, text: str) -> int:
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    response = client.post(
        f"{root}/tokenize",
        json={"model": model, "prompt": text},
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload.get("count"), int):
        return payload["count"]
    return len(payload.get("tokens") or [])


def build_prompt(client: httpx.Client, base: str, model: str, target: int) -> tuple[str, int]:
    base_count = max(1, count_tokens(client, base, model, BASE_TEXT))
    repeats = max(1, target // base_count)
    text = BASE_TEXT * repeats
    actual = count_tokens(client, base, model, text)
    return text, actual


def memory_mb(host: str, user: str) -> int | None:
    if not host:
        return None
    try:
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=5",
                f"{user}@{host}",
                "awk '/MemAvailable/{print $2}' /proc/meminfo",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        parts = completed.stdout.strip().split()
        return int(parts[0]) // 1024 if parts else None
    except Exception:  # noqa: BLE001
        return None


def chat_once(
    client: httpx.Client,
    base: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Read the material and return only JSON.",
            },
            {
                "role": "user",
                "content": 'Return {"ok": true}.\n\nMaterial:\n' + prompt,
            },
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    response = client.post(f"{base}/chat/completions", json=payload)
    if response.status_code == 400 and (
        "response_format" in response.text or "chat_template_kwargs" in response.text
    ):
        payload.pop("response_format", None)
        payload.pop("chat_template_kwargs", None)
        started = time.perf_counter()
        response = client.post(f"{base}/chat/completions", json=payload)
    latency_ms = int((time.perf_counter() - started) * 1000)
    result = {
        "status_code": response.status_code,
        "latency_ms": latency_ms,
    }
    if response.status_code != 200:
        result["error"] = response.text[:500]
        return result
    data = response.json()
    usage = data.get("usage") or {}
    result.update(
        {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "content_chars": len(
                str((data.get("choices") or [{}])[0].get("message", {}).get("content", ""))
            ),
        }
    )
    return result


def main() -> int:
    args = parse_args()
    base = api_base(args.base_url)
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    results = []
    with httpx.Client(timeout=args.timeout) as client:
        for target in sizes:
            prompt, actual_tokens = build_prompt(client, base, args.model, target)
            before = memory_mb(args.ssh_host, args.ssh_user)
            outcome = chat_once(client, base, args.model, prompt, args.max_tokens)
            after = memory_mb(args.ssh_host, args.ssh_user)
            outcome.update(
                {
                    "target_tokens": target,
                    "built_tokens": actual_tokens,
                    "memory_before_mb": before,
                    "memory_after_mb": after,
                }
            )
            results.append(outcome)
            print(json.dumps(outcome, ensure_ascii=False), flush=True)
    output = {
        "model": args.model,
        "base_url": base,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {path}", flush=True)
    return 0 if all(item.get("status_code") == 200 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
