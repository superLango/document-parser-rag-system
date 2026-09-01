"""完全复刻后端调用路径(OpenAICompatibleClient.complete) 调用 31510。

后端: llm_extractor._call_llm → OpenAICompatibleClient.complete(messages, json_mode,
       temperature, max_tokens, timeout, top_p, top_k, enable_thinking)
本脚本用同一 client 类 + 同一参数路径, 读真实 prompt, 打印响应。
若此脚本返回 [] → 后端 client 类本身问题; 若返回 JSON → 前端链路另有差异。

用法: python3 scripts/call_31510_via_client.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path('/home/grainuser/hansonDoc_RAG/backend')))

from app.services.llm.llm_client import OpenAICompatibleClient  # noqa: E402

PROMPT = "/home/grainuser/hansonDoc_RAG/qa/evaluation/results/chem_prompt_31510_REAL.json"
BASE_URL = "http://192.168.0.65:31510/v1"
MODEL = "qwen3.5"
API_KEY = "auozora"


async def main():
    p = json.load(open(PROMPT, encoding="utf-8"))
    client = OpenAICompatibleClient(
        base_url=BASE_URL, model=MODEL, api_key=API_KEY, timeout=300,
    )
    system, user = p.get("system", ""), p.get("user", "")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    print(f"调用后端 client 类: base_url={client.base_url} model={client.model} timeout={client.timeout}")
    print(f"  实际请求 URL: {client.base_url}/chat/completions")
    print(f"  system_len={len(system)} user_len={len(user)}", flush=True)
    print(f"  payload 字段: model/messages/temperature/max_tokens=80000/top_p=0.1/top_k=20/enable_thinking=False", flush=True)
    try:
        content = await client.complete(
        messages,
        json_mode=False,
        temperature=0.0,
        max_tokens=80000,
        timeout=300,
        top_p=0.1,
        top_k=20,
        enable_thinking=False,
    )
        print(f"响应 len={len(content or '')}")
        print(f"响应 head(500):\n{(content or '')[:500]}")
        (Path('/home/grainuser/hansonDoc_RAG/qa/evaluation/results/via_client_response.txt')).write_text(content or "", encoding="utf-8")
        print("已保存: qa/evaluation/results/via_client_response.txt")
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {str(exc)[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
