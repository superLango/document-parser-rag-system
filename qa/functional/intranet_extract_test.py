"""内网 LLM 整段抽取测试：读取预生成的 prompt，调用内网 qwen3.5，保存结果。

用法（在能访问内网 192.168.0.65 的环境执行）：
    cd /home/grainuser/hansonDoc_RAG
    backend/.venv/bin/python qa/functional/intranet_extract_test.py
输出保存到 qa/evaluation/results/gb1220_intranet_test/：
    raw_response.json   完整 LLM 响应
    parsed_records.json 解析出的记录数组
    meta.json           usage / finish_reason / 耗时 / 错误
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[2] / "qa/evaluation/results/gb1220_intranet_test"
LLM_URL = "http://192.168.0.65:31510/v1/chat/completions"
MODEL = "qwen3.5"
API_KEY = "auozora"
MAX_TOKENS = 100000  # 最大输出预算（窗口 131072）


def parse_records(content: str):
    """从模型输出中解析 JSON 数组，容错 thinking/围栏残留。"""
    t = content.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        data = json.loads(t)
    except Exception:
        # 尝试提取最后一个完整的 JSON 数组
        for m in re.finditer(r"\[.*?\]", t, re.S):
            try:
                data = json.loads(m.group(0))
                break
            except Exception:
                continue
        else:
            return [], t[:300]
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    return [r for r in data if isinstance(r, dict)], ""


def main():
    if not (BASE_DIR / "prompt.json").exists():
        print(f"缺少 prompt.json：{BASE_DIR}"); sys.exit(1)
    prompt = json.loads((BASE_DIR / "prompt.json").read_text(encoding="utf-8"))
    system, user = prompt["system"], prompt["user"]
    print(f"完整上下文: {prompt.get('context_chars')} 字符 / {prompt.get('blocks')} 块")
    print(f"调用内网模型 {MODEL} @ {LLM_URL}，max_tokens={MAX_TOKENS} ...", flush=True)

    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.time()
    error = None
    raw = None
    try:
        with httpx.Client(timeout=None) as client:  # 长输出不设超时
            resp = client.post(LLM_URL, json=body, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            })
            resp.raise_for_status()
            raw = resp.json()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        print(f"调用失败: {error}", flush=True)

    elapsed = round(time.time() - t0, 1)
    (BASE_DIR / "raw_response.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    if raw is None:
        (BASE_DIR / "meta.json").write_text(
            json.dumps({"elapsed_sec": elapsed, "error": error}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("结果已保存（失败）"); return

    choice = (raw.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    usage = raw.get("usage") or {}
    recs, parse_err = parse_records(content)
    (BASE_DIR / "parsed_records.json").write_text(
        json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {
        "elapsed_sec": elapsed,
        "finish_reason": choice.get("finish_reason"),
        "usage": usage,
        "parse_error": parse_err or None,
        "model": raw.get("model"),
    }
    (BASE_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    brands = {}
    for r in recs:
        brands.setdefault(r.get("材料牌号") or "", []).append(r)
    print(f"完成，耗时 {elapsed}s")
    print(f"finish_reason={choice.get('finish_reason')} | usage={usage}")
    print(f"records={len(recs)} 牌号={len(brands)} | parse_err={parse_err or '无'}")
    if recs:
        print("样例:", json.dumps(recs[0], ensure_ascii=False)[:200])
    print(f"结果已保存到 {BASE_DIR}")


if __name__ == "__main__":
    main()
