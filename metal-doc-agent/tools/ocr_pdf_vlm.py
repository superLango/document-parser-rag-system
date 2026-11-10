"""OCR a scanned PDF with the served Qwen3.5 vision model.

The engine's ``mock`` OCR reads markdown, and ``glm`` needs a GLM-OCR service.
When neither is available, this tool rasterizes each PDF page and asks the
served multimodal Qwen3.5 model to transcribe it to Markdown with HTML tables
(the TableGrid parser only understands HTML ``<table>`` blocks).

Usage:
    python -m tools.ocr_pdf_vlm --pdf "F:\\paike\\lims\\派克标准拆分文件\\GBT2965-2007.pdf" \
      --out runs/gbt2965_2007/source.md --base-url http://192.168.1.35:9991/v1
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import time
import urllib.request
from pathlib import Path

import pymupdf

PROMPT = (
    "请把这张标准文档页面转录为 Markdown。要求：\n"
    "1. 正文按阅读顺序输出，保留标题层级；\n"
    "2. 表格必须输出为 HTML <table>，单元格文字逐字保留，不要合并或改写数值；\n"
    "3. 不要输出解释、页码或水印（忽略 bzwn/bzfxw 水印）。"
)
GLM_PROMPT = (
    "请完整识别图片内容，按阅读顺序输出 Markdown；表格必须转换为 HTML <table> 格式，"
    "保留所有行列与数值，不要改写；不要输出解释。"
)
PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
PIPE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _chat(base_url: str, model: str, image_png: bytes) -> str:
    data_url = "data:image/png;base64," + base64.b64encode(image_png).decode()
    is_glm = model.lower().startswith("glm")
    image_part = {"type": "image_url", "image_url": {"url": data_url}}
    text_part = {"type": "text", "text": GLM_PROMPT if is_glm else PROMPT}
    content = [image_part, text_part] if is_glm else [text_part, image_part]
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0,
    }
    if not is_glm:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    payload = json.loads(urllib.request.urlopen(request, timeout=600).read())
    return payload["choices"][0]["message"]["content"]


def _strip_fence(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def _pipe_tables_to_html(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if (
            PIPE_ROW.match(lines[index])
            and index + 1 < len(lines)
            and PIPE_SEP.match(lines[index + 1])
        ):
            header = _cells(lines[index])
            body: list[list[str]] = []
            index += 2
            while index < len(lines) and PIPE_ROW.match(lines[index]):
                body.append(_cells(lines[index]))
                index += 1
            output.append("<table>")
            output.append("<tr>" + "".join(f"<th>{cell}</th>" for cell in header) + "</tr>")
            for row in body:
                output.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
            output.append("</table>")
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def _cells(line: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in line.strip().strip("|").split("|")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url", default="http://192.168.1.35:9991/v1")
    parser.add_argument("--model", default="Qwen3.5-9B")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args(argv)

    pdf = pymupdf.open(args.pdf)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pages: list[str] = []
    started = time.time()
    for index in range(pdf.page_count):
        page = pdf.load_page(index)
        pix = page.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csRGB, alpha=False)
        text = _strip_fence(_chat(args.base_url, args.model, pix.tobytes("png")))
        text = _pipe_tables_to_html(text)
        pages.append(f"<!-- page: {index + 1} -->\n\n{text}")
        print(f"[{index + 1}/{pdf.page_count}] {len(text)} chars", flush=True)
    out_path.write_text("\n\n".join(pages) + "\n", encoding="utf-8")
    print(json.dumps({"pages": pdf.page_count, "seconds": round(time.time() - started, 1), "out": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
