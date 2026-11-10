"""Qwen3.5-9B smoke test: non-thinking chat + JSON extraction.

Run on the model host (or any host that can reach 9989):
    python tools/model_smoke/qwen_smoke.py --base http://127.0.0.1:9989/v1
"""

from __future__ import annotations

import argparse
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:9989/v1")
    parser.add_argument("--model", default="Qwen3.5-9B")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    with httpx.Client(timeout=args.timeout) as client:
        models = client.get(f"{args.base}/models").json()
        print("models:", [item["id"] for item in models.get("data", [])])

        simple = client.post(
            f"{args.base}/chat/completions",
            json={
                "model": args.model,
                "messages": [{"role": "user", "content": "只回复：ok"}],
                "temperature": 0,
                "max_tokens": 16,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        simple.raise_for_status()
        print("simple:", repr(simple.json()["choices"][0]["message"]["content"]))

        extraction = client.post(
            f"{args.base}/chat/completions",
            json={
                "model": args.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是金属材料标准抽取器，只输出 JSON，不要解释。",
                    },
                    {
                        "role": "user",
                        "content": (
                            "表头：牌号 | 抗拉强度Rm/MPa(不小于) | 断后伸长率A/%(不小于)。"
                            "数据行：2A14 | 430 | 10。"
                            "请输出 JSON：{\"grade\": string, \"condition\": null, "
                            "\"properties\": {\"Rm\": {\"raw\": string, \"value\": number, "
                            "\"unit\": string, \"comparator\": \"min\"}, "
                            "\"A\": {\"raw\": string, \"value\": number, \"unit\": string, "
                            "\"comparator\": \"min\"}}}"
                        ),
                    },
                ],
                "temperature": 0,
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        extraction.raise_for_status()
        raw = extraction.json()["choices"][0]["message"]["content"]
        print("json_chars:", len(raw))
        print("has_think:", "<think" in raw.lower())
        print("json_head:", raw[:600])
        parsed = json.loads(raw)
        print("parsed_ok:", True)
        print("grade:", parsed.get("grade"))
        print("properties:", list(parsed.get("properties", {}).keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
