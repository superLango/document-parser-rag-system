"""并发探针: 验证 31510(qwen3.5) 在并发请求下是否返回 []。

用成功版 body(带 top_p/top_k/enable_thinking), 按 N 并发同时发相同请求,
统计每个请求的响应: 是否为空数组 [] / 正常 JSON / 报错。
如果 N=1 正常、N≥2 变空 → 确认服务端并发限制, 解法=后端 LLM 并发调 1。

用法:
    python3 scripts/concurrency_probe_31510.py [--concurrency N] [--json-mode]
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

BASE = "/home/grainuser/hansonDoc_RAG/qa/evaluation/results"
PROMPT = f"{BASE}/chem_prompt_31510.json"
LLM_URL = "http://192.168.0.65:31510/v1/chat/completions"
MODEL = "qwen3.5"
API_KEY = "auozora"


def build_body(p, json_mode: bool) -> dict:
    return {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": p.get("system", "")},
            {"role": "user", "content": p.get("user", "")},
        ],
        "max_tokens": 80000,
        "temperature": 0.0,
        "top_p": 0.1,
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    }


async def one(client, body, idx):
    t0 = time.time()
    try:
        r = await client.post(LLM_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json=body, timeout=300)
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        n = len(content or "")
        head = (content or "")[:80].replace("\n", " ")
        verdict = "JSON" if (content or "").strip().startswith("[") or (content or "").strip().startswith("{") else ("EMPTY-[]" if n == 2 and "[]" in head else f"other({n})")
        print(f"  [#{idx}] {r.status_code} 耗时{time.time()-t0:.1f}s len={n} verdict={verdict} head={head}", flush=True)
        return verdict
    except Exception as exc:
        print(f"  [#{idx}] ERROR {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        return "ERROR"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--json-mode", action="store_true")
    ap.add_argument("--prompt", default=PROMPT)
    args = ap.parse_args()
    p = json.load(open(args.prompt, encoding="utf-8"))
    body = build_body(p, args.json_mode)
    print(f"并发探针: N={args.concurrency} json_mode={args.json_mode} user_chars={p.get('user_chars')}")
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=300) as client:
        async def task(i):
            async with sem:
                return await one(client, body, i)
        res = await asyncio.gather(*(task(i) for i in range(args.concurrency)))
    from collections import Counter
    print("汇总:", dict(Counter(res)))


if __name__ == "__main__":
    asyncio.run(main())
