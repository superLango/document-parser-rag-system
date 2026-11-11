"""GLM-OCR smoke test: render one PDF page and call the table prompt.

Run on the model host with the hansonDoc_RAG backend venv:
    backend/.venv/bin/python tools/model_smoke/glm_ocr_smoke.py \
      --pdf /tmp/qdu302.pdf --page 5 --needle 430
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import httpx
import pymupdf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--page", type=int, default=1, help="1-based page number")
    parser.add_argument("--url", default="http://127.0.0.1:9977/v1/chat/completions")
    parser.add_argument("--model", default="GLM-OCR")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--needle", default="430")
    parser.add_argument("--out", default="/tmp/glm_smoke.json")
    parser.add_argument("--image-out", default="/tmp/glm_smoke_page.png")
    parser.add_argument(
        "--prompt",
        default=(
            "请将图片中的表格完整识别并转换为 HTML <table> 格式输出，"
            "保留所有行列内容，不要输出解释。"
        ),
    )
    args = parser.parse_args()

    doc = pymupdf.open(args.pdf)
    if not 1 <= args.page <= doc.page_count:
        raise SystemExit(f"page out of range: 1..{doc.page_count}")
    page = doc.load_page(args.page - 1)
    pix = page.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csRGB, alpha=False)
    image_bytes = pix.tobytes("png")
    Path(args.image_out).write_bytes(image_bytes)

    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": args.prompt},
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0,
    }

    resp = httpx.post(args.url, json=payload, timeout=180)
    print("HTTP", resp.status_code)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    print("chars", len(content))
    print("has_table", "<table" in content.lower())
    print("has_needle", args.needle in content)
    print("--- content head ---")
    print(content[:1500])
    Path(args.out).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
