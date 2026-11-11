"""End-to-end smoke for the model service clients.

Run from the laptop against the model host:
    python tools/model_smoke/client_smoke.py \
      --image runs/glm_page.png \
      --glm-url http://192.168.1.35:9977/v1 \
      --qwen-url http://192.168.1.35:9989/v1 \
      --layout-url http://192.168.1.35:9978
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.clients import GlmOcrClient, LayoutClient, QwenClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--glm-url", default="http://192.168.1.35:9977/v1")
    parser.add_argument("--qwen-url", default="http://192.168.1.35:9989/v1")
    parser.add_argument("--layout-url", default="http://192.168.1.35:9978")
    parser.add_argument("--qwen-model", default="Qwen3.5-9B")
    parser.add_argument("--glm-model", default="GLM-OCR")
    parser.add_argument("--needle", default="430")
    args = parser.parse_args()

    image = Path(args.image).read_bytes()
    failures: list[str] = []

    with GlmOcrClient(args.glm_url, args.glm_model) as glm:
        glm_models = glm.health()
        print("glm models:", glm_models)
        if args.glm_model not in glm_models:
            failures.append("glm model not listed")
        ocr_text = glm.ocr_image(image, "table")
        print("glm chars:", len(ocr_text), "has_table:", "<table" in ocr_text.lower())
        print("glm has needle:", args.needle in ocr_text)
        if "<table" not in ocr_text.lower():
            failures.append("glm output has no <table>")
        if args.needle not in ocr_text:
            failures.append("glm output missing needle")

    with QwenClient(args.qwen_url, args.qwen_model) as qwen:
        qwen_models = qwen.health()
        print("qwen models:", qwen_models)
        if args.qwen_model not in qwen_models:
            failures.append("qwen model not listed")
        raw = qwen.chat(
            [
                {"role": "system", "content": "只输出 JSON，不要解释。"},
                {
                    "role": "user",
                    "content": (
                        "表头：牌号 | 抗拉强度Rm/MPa(不小于) | 断后伸长率A/%(不小于)。"
                        "数据行：2A14 | 430 | 10。输出 JSON，包含 grade 与 properties。"
                    ),
                },
            ],
            json_mode=True,
            max_tokens=512,
        )
        print("qwen json chars:", len(raw), "has_think:", "<think" in raw.lower())
        try:
            parsed = json.loads(raw)
            print("qwen parsed:", parsed.get("grade"), list(parsed.get("properties", {})))
        except json.JSONDecodeError as exc:
            failures.append(f"qwen output is not JSON: {exc}")
        if "<think" in raw.lower():
            failures.append("qwen output contains <think>")

    with LayoutClient(args.layout_url) as layout:
        health = layout.health()
        print("layout health:", health)
        if not health.get("model_loaded"):
            failures.append("layout model not loaded")
        blocks = layout.analyze(image, page_index=5)
        types = sorted({block.type for block in blocks})
        print("layout blocks:", len(blocks), "types:", types)
        if not any(block.type == "table" for block in blocks):
            failures.append("layout found no table block")

    if failures:
        print("FAILED:", failures)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
