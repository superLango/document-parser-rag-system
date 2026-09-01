"""调用内网 LLM(192.168.0.65:31510)复现化学成分抽取 -- 诊断脚本。

用法(需可访问内网 192.168.0.65 的环境):
    python3 scripts/call_31510_chem.py [--prompt PATH] [--json-mode] [--max-tokens N]
产物(保存到 qa/evaluation/results/):
    llm_31510_response.json    完整响应
    llm_31510_response.txt     原始 content
"""

import argparse
import json
import time
from pathlib import Path

import httpx

BASE = "/home/grainuser/hansonDoc_RAG/qa/evaluation/results"
PROMPT_DEFAULT = f"{BASE}/chem_prompt_31510_REAL.json"
LLM_URL = "http://192.168.0.65:31510/v1/chat/completions"
MODEL = "qwen3.5"
API_KEY = "auozora"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default=PROMPT_DEFAULT, help="prompt 文件(含 system/user)")
    ap.add_argument("--json-mode", action="store_true", help="加 response_format json_object")
    ap.add_argument("--max-tokens", type=int, default=80000)
    ap.add_argument("--top-p", type=float, default=None, help="默认不传(后端 None 时不传)")
    ap.add_argument("--top-k", type=int, default=None, help="默认不传")
    ap.add_argument("--enable-thinking", type=str, default=None, choices=["true", "false"], help="默认不传")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    args.top_p = args.top_p
    args.top_k = args.top_k
    if args.enable_thinking is not None:
        args.enable_thinking = args.enable_thinking == "true"

    p = json.load(open(args.prompt, encoding="utf-8"))
    # 完全复刻后端 OpenAICompatibleClient.complete() 的 payload 构造:
    #   payload = {model, messages, temperature}
    #   + max_tokens(布尔非空) + top_p + top_k + chat_template_kwargs(enable_thinking) + response_format(json_mode)
    # 默认即完全模拟后端 OpenAICompatibleClient.complete() 的 payload:
    #   payload = {model, messages, temperature}
    #   + max_tokens + top_p(0.1) + top_k(20) + chat_template_kwargs{enable_thinking:false}
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": p.get("system", "")},
            {"role": "user", "content": p.get("user", "")},
        ],
        "temperature": 0.0,
        "max_tokens": int(args.max_tokens),
        "top_p": 0.1,
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if args.json_mode:
        body["response_format"] = {"type": "json_object"}

    print(f"调用 {LLM_URL} model={MODEL} max_tokens={args.max_tokens} json_mode={args.json_mode}")
    print(f"  system_chars={p.get('system_chars')} user_chars={p.get('user_chars')} blocks={p.get('blocks')}")
    t0 = time.time()
    try:
        # trust_env=False: 忽略 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 环境代理,
        # 直连内网 31510(避免 socks 代理报 Unknown scheme / 走代理不可达)
        resp = httpx.post(
            LLM_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=body,
            timeout=args.timeout,
            trust_env=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"请求异常: {type(exc).__name__}: {exc}")
        return
    dt = time.time() - t0
    print(f"HTTP {resp.status_code}  耗时 {dt:.1f}s")

    # 保存完整请求(供对比后端 payload)
    (Path(BASE) / "llm_31510_request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    # 保存完整响应
    out_json = Path(BASE) / "llm_31510_response.json"
    out_txt = Path(BASE) / "llm_31510_response.txt"
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    (out_json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        content = resp.text
    (out_txt).write_text(content, encoding="utf-8")

    print(f"响应 length={len(content or '')}")
    print(f"响应 head(500):\n{(content or '')[:500]}")
    print(f"\n已保存: {out_json}\n        {out_txt}")


if __name__ == "__main__":
    main()
