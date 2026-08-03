"""Popo VLM 推理引擎（重写，不复用 app/popo/ 原代码）。

使用 Qwen3-VL 4B 模型对 OCR 输出做四大后处理：
1. 文本截断分析（Text Truncation）：跨页段落合并
2. 标题层级分析（Title Hierarchy）：识别标题层级
3. 图文关联分析（Image-Text Correlation）：图片与题注对应
4. 表格截断分析（Table Merge）：跨页表格合并

批处理优化：
- 模型懒加载单例（首次推理时加载，后续复用）
- 动态分块（按页数分 chunk，减少单次推理 token 量）
- 图片批量渲染（一次渲染所有需要的页面）
- 四任务串行推理（GPU 串行约束），但过滤阶段高效
"""

from __future__ import annotations

import io
import re
import logging
import base64
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────────────

_TERMINATION_CHARS = set(".。?！？¿¡؟۔ฯ：:;；……")
_CLOSE_CHARS = set("'\"'\u201d\u2019」】）)")
_TERMINATION_PATTERN = re.compile("[" + re.escape("".join(_TERMINATION_CHARS)) + "]")

# 列表项前缀正则
_LIST_ITEM_PATTERN = re.compile(
    r"""^(?:
        \d+[\.\)] |
        \d+） |
        [a-zA-Z][\.\)] |
        [①-⑳㉑-㉟] |
        [•▪▫] |
        [IVXLCDM]+\. |
        - |
        \$ |
        \\t |
        [\[\(「【（] |
        第[一二三四五六七八九十百千万][条节章]
    )\s*""",
    re.IGNORECASE | re.VERBOSE,
)

# chunk 分块参数
_CHUNK_SIZE = 10  # 每 chunk ~10 页（质量与速度最优平衡点）
_CHUNK_OVERLAP = 1  # 页重叠

# 模型配置默认值
_DEFAULT_MAX_NEW_TOKENS = 2048


# ── 模型管理 ───────────────────────────────────────────────────────────────

_MODEL = None
_PROCESSOR = None
_VLLM_CLIENT = None
_IMAGE_CACHE: dict[tuple, str] = {}


def _get_vllm_client():
    """获取 vLLM OpenAI 兼容客户端（单例）。"""
    global _VLLM_CLIENT
    if _VLLM_CLIENT is not None:
        return _VLLM_CLIENT
    import os
    from openai import OpenAI
    url = os.environ.get("POPO_VLLM_URL", "http://localhost:9999/v1")
    key = os.environ.get("POPO_VLLM_KEY", "EMPTY")
    _VLLM_CLIENT = OpenAI(base_url=url, api_key=key)
    logger.info("vLLM 客户端已连接: %s", url)
    return _VLLM_CLIENT


def _load_model():
    """懒加载 Qwen3-VL 模型（单例，仅 transformers 后端使用）。"""
    global _MODEL, _PROCESSOR
    if _MODEL is not None and _PROCESSOR is not None:
        return _MODEL, _PROCESSOR

    import os
    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    model_path = os.environ.get("POPO_MODEL_PATH", "models/MinerU-Popo")

    logger.info("加载 Popo 模型: %s", model_path)
    _MODEL = Qwen3VLForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    _PROCESSOR = AutoProcessor.from_pretrained(
        model_path,
        tokenizer_kwargs={"padding_side": "left"},
    )
    logger.info("Popo 模型加载完成")
    return _MODEL, _PROCESSOR


def _is_vllm_backend() -> bool:
    """是否使用 vLLM 后端。"""
    import os
    return os.environ.get("POPO_INFERENCE_BACKEND", "transformers") == "vllm"


def _generate(prompt: str, base64_image: str | None) -> str:
    """调用 VLM 生成响应（自动选择 vLLM 或 transformers 后端）。

    Args:
        prompt: 文本 prompt（以 ``<image>\\n`` 开头表示需要图片）。
        base64_image: base64 编码的 JPEG 图片（None 则不传图片）。

    Returns:
        模型生成的文本。
    """
    if _is_vllm_backend():
        return _generate_vllm(prompt, base64_image)
    return _generate_transformers(prompt, base64_image)


def _generate_vllm(prompt: str, base64_image: str | None) -> str:
    """vLLM 后端推理（通过 OpenAI 兼容 API）。"""
    import os
    max_new_tokens = int(os.environ.get("POPO_MAX_NEW_TOKENS", str(_DEFAULT_MAX_NEW_TOKENS)))
    model_name = os.environ.get("POPO_VLLM_MODEL", "Popo")
    client = _get_vllm_client()

    # 移除 prompt 开头的 <image> 标记（vLLM 用 image_url 传图）
    text = prompt
    if text.startswith("<image>"):
        text = text[len("<image>"):].lstrip()
    text = text[:100000] if len(text) > 100000 else text

    content = []
    if base64_image:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
        })
    content.append({"type": "text", "text": text})

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_new_tokens,
    )
    return response.choices[0].message.content if response.choices else ""


def _generate_transformers(prompt: str, base64_image: str | None) -> str:
    """transformers 后端推理。"""
    import os
    import torch

    model, processor = _load_model()
    max_new_tokens = int(os.environ.get("POPO_MAX_NEW_TOKENS", str(_DEFAULT_MAX_NEW_TOKENS)))

    content = []
    if base64_image:
        content.append({
            "type": "image",
            "image": f"data:image/jpeg;base64,{base64_image}",
        })
    text = prompt[:100000] if len(prompt) > 100000 else prompt
    content.append({"type": "text", "text": text})

    messages = [{"role": "user", "content": content}]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)

    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)

    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated_ids)]
    output = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    return output[0] if output else ""


# ── 图片渲染 ───────────────────────────────────────────────────────────────

def _render_pages_to_image(pdf_path: str, pages: list[int], border_width: int = 5) -> str:
    """渲染 PDF 页面并拼接为单张长图，返回 base64 编码（带缓存）。

    Args:
        pdf_path: PDF 文件路径。
        pages: 页码列表（1-based）。
        border_width: 页面间边框宽度（像素）。

    Returns:
        base64 编码的 JPEG 图片字符串。
    """
    if not pages:
        pages = [1]

    # 缓存：同一 PDF + 同一页面集合只渲染一次
    cache_key = (pdf_path, tuple(sorted(pages)))
    if cache_key in _IMAGE_CACHE:
        return _IMAGE_CACHE[cache_key]

    doc = fitz.open(pdf_path)
    pil_images: list[Image.Image] = []
    try:
        for page_num in pages:
            if page_num < 1 or page_num > len(doc):
                continue
            page = doc[page_num - 1]
            # 降低 DPI 以减少图片大小（VLM 不需要高分辨率）
            zoom = 0.5  # 降到 36 DPI，减少视觉 token 数量
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("jpeg")))

            # 标注页码
            draw = ImageDraw.Draw(img)
            avg_size = (page.rect.width + page.rect.height) / 2
            font_size = int(avg_size * 0.1)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
            draw.text((10, 10), str(page_num), fill=(255, 0, 0), font=font)
            pil_images.append(img)
    finally:
        doc.close()

    if not pil_images:
        return ""

    # 垂直拼接
    total_h = sum(img.height for img in pil_images) + border_width * (len(pil_images) - 1)
    max_w = max(img.width for img in pil_images)
    result = Image.new("RGB", (max_w, total_h), color="white")

    y = 0
    for i, img in enumerate(pil_images):
        x = (max_w - img.width) // 2
        result.paste(img, (x, y))
        if i < len(pil_images) - 1:
            y_border = y + img.height
            ImageDraw.Draw(result).rectangle(
                [0, y_border, max_w - 1, y_border + border_width - 1], fill="black"
            )
            y = y_border + border_width
        else:
            y += img.height

    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=60, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    _IMAGE_CACHE[cache_key] = b64
    return b64


# ── 文本工具 ───────────────────────────────────────────────────────────────

def _get_head_sentence(text: str) -> str:
    """提取首句。"""
    text = text.strip()
    if not text:
        return text
    m = _TERMINATION_PATTERN.search(text)
    return text[:m.end()].strip() if m else text


def _get_tail_sentence(text: str) -> str:
    """提取末句。"""
    text = text.strip()
    if not text:
        return text
    parts = [p.strip() for p in _TERMINATION_PATTERN.split(text) if p.strip()]
    return parts[-1] if parts else text


def _is_list_item(s: str) -> bool:
    """判断是否为列表项前缀。"""
    return _LIST_ITEM_PATTERN.match(s) is not None


def _merge_rules(str1: str, str2: str) -> bool:
    """文本截断启发式：判断 str1 是否可能被截断到 str2。

    规则：
    - str1 末尾不是终止符（句号/问号/冒号等）
    - str1 长度 >= 10
    - str2 不是列表项
    - 不含 tab
    - 两者不以数字开头
    """
    if not str1 or not str2:
        return False
    s1 = str1.strip()
    if len(s1) < 10:
        return False
    # 末尾是终止符 → 不截断
    if s1 and s1[-1] in _TERMINATION_CHARS:
        return False
    # 末尾是闭合符号且前一个字符是终止符 → 不截断
    if len(s1) > 1 and s1[-1] in _CLOSE_CHARS and s1[-2] in _TERMINATION_CHARS:
        return False
    if _is_list_item(str2):
        return False
    if "\t" in str1 or "\t" in str2:
        return False
    if str1[0].isdigit() and str2[0].isdigit():
        return False
    return True


def _bbox_to_prompt_str(bbox: list[float]) -> list[str]:
    """将归一化 bbox 转为 prompt 用的字符串列表。

    坐标顺序从 [x1, y1, x2, y2] 变为 [y1, x1, y2, x2]，
    乘以 1000 转为整数（千分比）。
    """
    x1, y1, x2, y2 = bbox[:4]
    return [
        str(int(y1 * 1000)),
        str(int(x1 * 1000)),
        str(int(y2 * 1000)),
        str(int(x2 * 1000)),
    ]


# ── 过滤器 ─────────────────────────────────────────────────────────────────

def _filter_contd(doc_blocks: list[dict]) -> list[dict]:
    """过滤文本截断分析候选块。

    找相邻的 text/list_item 块对，用 _merge_rules 判断是否可能截断。
    """
    potential: list[int] = []
    for i, block in enumerate(doc_blocks):
        if block["type"] not in ("text", "list_item"):
            continue
        for j in range(i + 1, len(doc_blocks)):
            nxt = doc_blocks[j]
            # 遇到 equation/title → 中断
            if "equation" in nxt["type"] or "title" in nxt["type"]:
                break
            if nxt["type"] in ("text", "list_item") and _merge_rules(block["content"], nxt["content"]):
                if i not in potential:
                    potential.append(i)
                if j not in potential:
                    potential.append(j)
                break

    judge_blocks = []
    for idx in potential:
        b = doc_blocks[idx]
        text = b["content"]
        head = _get_head_sentence(text)
        tail = _get_tail_sentence(text)
        short = head if head == tail else f"{head} ... {tail}"
        if len(short) > 103:
            short = short[:50] + "..." + short[-50:]
        judge_blocks.append({
            "idx": idx,
            "content": short,
            "page": b["page"],
            "bbox": _bbox_to_prompt_str(b["bbox"]),
        })
    return judge_blocks


def _filter_title(doc_blocks: list[dict]) -> list[dict]:
    """过滤标题层级分析候选块。"""
    judge_blocks = []
    for i, b in enumerate(doc_blocks):
        if b["type"] in ("title", "TOC-title", "section-title"):
            judge_blocks.append({
                "idx": i,
                "content": b["content"][:50],
                "page": b["page"],
                "bbox": _bbox_to_prompt_str(b["bbox"]),
            })
    return judge_blocks


def _filter_image(doc_blocks: list[dict]) -> list[dict]:
    """过滤图文关联分析候选块。

    筛选 image/caption/table/title 等视觉相关块。
    """
    visual_types = {
        "image", "table", "image_caption", "table_caption",
        "image_footnote", "table_footnote", "title",
        "chart", "figure",
    }
    judge_blocks = []
    for i, b in enumerate(doc_blocks):
        typ = b["type"]
        # seal → image
        if typ == "seal":
            typ = "image"
        if typ not in visual_types:
            continue
        # image/table 的 content 设为 "None"
        content = "None" if typ in ("image", "table") else b["content"][:50]
        judge_blocks.append({
            "idx": i,
            "type": typ,
            "content": content,
            "page": b["page"],
            "bbox": _bbox_to_prompt_str(b["bbox"]),
        })
    return judge_blocks


def _filter_table_merge(doc_blocks: list[dict]) -> list[dict]:
    """过滤跨页表格合并候选。

    找相邻页的表格对，提取首尾行用于合并判断。
    """
    tables_by_page: dict[int, list[int]] = {}
    for i, b in enumerate(doc_blocks):
        if b["type"] == "table":
            tables_by_page.setdefault(b["page"], []).append(i)

    if len(tables_by_page) < 2:
        return []

    merge_inputs = []
    sorted_pages = sorted(tables_by_page.keys())
    for p in range(len(sorted_pages) - 1):
        p1, p2 = sorted_pages[p], sorted_pages[p + 1]
        if p2 != p1 + 1:
            continue
        t1_idx = tables_by_page[p1][-1]
        t2_idx = tables_by_page[p2][0]
        # 提取首尾行（简化版：用 content 的前几行）
        t1_html = doc_blocks[t1_idx]["content"]
        t2_html = doc_blocks[t2_idx]["content"]
        upper_rows = _extract_last_row(t1_html)
        lower_rows = _extract_first_row(t2_html)
        if upper_rows and lower_rows:
            merge_inputs.append({
                "table1_idx": t1_idx,
                "table2_idx": t2_idx,
                "upper_rows": upper_rows,
                "lower_rows": lower_rows,
            })
    return merge_inputs


def _extract_last_row(html: str) -> list[str]:
    """从 HTML 表格提取最后一行单元格内容。"""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")
        if not rows:
            return []
        cells = rows[-1].find_all(["td", "th"])
        return [c.get_text(strip=True) for c in cells]
    except Exception:
        return []


def _extract_first_row(html: str) -> list[str]:
    """从 HTML 表格提取第一数据行内容。"""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")
        if len(rows) < 2:
            return []
        cells = rows[1].find_all(["td", "th"])
        return [c.get_text(strip=True) for c in cells]
    except Exception:
        return []


# ── Prompt 构造 ────────────────────────────────────────────────────────────

def _build_prompt_contd(judge_blocks: list[dict]) -> str:
    """构造文本截断分析 prompt。"""
    lines = [
        f"<|id|>{b['idx']}<|page|>{b['page']}<|box|>{' '.join(b['bbox'])}<|content|>{b['content']}"
        for b in judge_blocks
    ]
    return f"<image>\nTruncation Detection: {chr(10).join(lines)}"


def _build_prompt_title(judge_blocks: list[dict]) -> str:
    """构造标题层级分析 prompt。"""
    lines = [
        f"<|id|>{b['idx']}<|page|>{b['page']}<|box|>{' '.join(b['bbox'])}<|content|>{b['content']}"
        for b in judge_blocks
    ]
    return f"<image>\nTitle Level Analysis: {chr(10).join(lines)}"


def _build_prompt_image(judge_blocks: list[dict]) -> str:
    """构造图文关联分析 prompt。"""
    lines = [
        f"<|id|>{b['idx']}<|type|>{b['type']}<|page|>{b['page']}<|box|>{' '.join(b['bbox'])}<|content|>{b['content']}"
        for b in judge_blocks
    ]
    return f"<image>\nImage-Text Correlation Analysis: {chr(10).join(lines)}"


def _build_prompt_table_merge(upper_rows: list[str], lower_rows: list[str]) -> str:
    """构造表格合并判断 prompt。"""
    return (
        f"## Table 1 (Previous Page - Last Table)\n\n"
        f"**Last Row(s) Data:**\n{upper_rows}\n\n---\n\n"
        f"## Table 2 (Current Page - First Table)\n\n"
        f"**First Data Row(s):**\n{lower_rows}"
    )


# ── 响应解析 ───────────────────────────────────────────────────────────────

def _parse_pairs(response: str) -> list[dict]:
    """解析 src_id → tgt_id 对（contd / image 任务）。"""
    results = []
    for line in response.strip().split("\n"):
        try:
            if "<|src_id|>" not in line or "<|tgt_id|>" not in line:
                continue
            src_part, tgt_part = line.split("<|tgt_id|>")
            src_id = src_part.split("<|src_id|>")[1]
            tgt_id = tgt_part.strip()
            results.append({"src_id": int(src_id), "tgt_id": int(tgt_id)})
        except (ValueError, IndexError):
            continue
    return results


def _parse_levels(response: str) -> list[dict]:
    """解析 id → level 对（title 任务）。"""
    results = []
    for line in response.strip().split("\n"):
        try:
            if "<|id|>" not in line or "<|level|>" not in line:
                continue
            id_part, level_part = line.split("<|level|>")
            idx = id_part.split("<|id|>")[1]
            level = int(level_part.strip())
            if level >= 0:
                results.append({"id": int(idx), "level": level})
        except (ValueError, IndexError):
            continue
    return results


# ── 动态分块 ───────────────────────────────────────────────────────────────

def _adaptive_chunk(items: list[dict], chunk_size: int = _CHUNK_SIZE) -> list[list[dict]]:
    """按页数动态分块，同一页面的块不会被拆分。

    Args:
        items: 待分块的 block 列表（已按 page 排序）。
        chunk_size: 每 chunk 目标页数。

    Returns:
        分块后的列表，每个子列表是一个 chunk。
    """
    if not items:
        return []

    sorted_items = sorted(items, key=lambda x: x["page"])
    pages = [item["page"] for item in sorted_items]
    unique_pages = sorted(set(pages))

    if len(unique_pages) <= chunk_size:
        return [sorted_items]

    # 按页数分块
    chunks = []
    start = 0
    while start < len(unique_pages):
        end_page = unique_pages[min(start + chunk_size - 1, len(unique_pages) - 1)]
        chunk = [item for item in sorted_items if unique_pages[start] <= item["page"] <= end_page]
        if chunk:
            chunks.append(chunk)
        start += chunk_size

    return chunks


# ── 主推理 ─────────────────────────────────────────────────────────────────

class PopoInference:
    """Popo VLM 推理引擎。"""

    @staticmethod
    def infer(
        pdf_path: str,
        popo_input: dict[str, list[dict]],
        output_dir: str | Path | None = None,
    ) -> list[dict]:
        """执行四大后处理任务，返回带 level/contd/image 字段的 doc_blocks。

        Args:
            pdf_path: PDF 文件路径（用于渲染页面图片）。
            popo_input: 归一化后的输入 ``{page_str: [blocks]}``。
            output_dir: 推理中间产物输出目录（None 则不保存）。

        Returns:
            doc_blocks 列表，每个 block 含原始字段 + level/contd/image/table_merge。
        """
        # 1. 展平 popo_input 为 doc_blocks
        doc_blocks: list[dict] = []
        idx = 1
        for page_str, blocks in popo_input.items():
            for block in blocks:
                block["page"] = int(page_str)
                block["id"] = idx
                idx += 1
                # 初始化后处理字段
                block["contd"] = -1
                block["level"] = -1
                block["image"] = -1
                block["table_merge"] = -1
                doc_blocks.append(block)

        logger.info("Popo 推理开始: %d 个 block", len(doc_blocks))

        # 2. 四任务过滤
        contd_blocks = _filter_contd(doc_blocks)
        title_blocks = _filter_title(doc_blocks)
        image_blocks = _filter_image(doc_blocks)
        table_merge_inputs = _filter_table_merge(doc_blocks)

        logger.info(
            "过滤完成: contd=%d, title=%d, image=%d, table_merge=%d",
            len(contd_blocks), len(title_blocks), len(image_blocks), len(table_merge_inputs),
        )

        # 3. 执行推理（扁平化并行：所有任务的所有 chunk 统一调度）
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 收集所有推理请求
        all_requests: list[dict] = []  # {task, chunk, prompt_fn, parse_fn}

        for task_name, blocks, build_fn, parse_fn in [
            ("contd", contd_blocks, _build_prompt_contd, _parse_pairs),
            ("title", title_blocks, _build_prompt_title, _parse_levels),
            ("image", image_blocks, _build_prompt_image, _parse_pairs),
        ]:
            if not blocks:
                continue
            chunks = _adaptive_chunk(blocks)
            logger.info("[%s] %d 个候选块，分为 %d chunk", task_name, len(blocks), len(chunks))
            for chunk in chunks:
                all_requests.append({
                    "task": task_name,
                    "chunk": chunk,
                    "pdf_path": pdf_path,
                    "build_fn": build_fn,
                    "parse_fn": parse_fn,
                })

        # table_merge 请求也加入
        for mi in table_merge_inputs:
            all_requests.append({
                "task": "table_merge",
                "merge_input": mi,
                "pdf_path": pdf_path,
            })

        def _execute_request(req):
            """执行单个推理请求。"""
            if req["task"] == "table_merge":
                mi = req["merge_input"]
                prompt = _build_prompt_table_merge(mi["upper_rows"], mi["lower_rows"])
                response = _generate(prompt, base64_image=None)
                if response and ("merge" in response.lower() or "合并" in response):
                    return {"task": "table_merge", "result": (mi["table1_idx"], mi["table2_idx"])}
                return {"task": "table_merge", "result": None}
            else:
                pages = sorted(set(b["page"] for b in req["chunk"]))
                base64_img = _render_pages_to_image(req["pdf_path"], pages)
                prompt = req["build_fn"](req["chunk"])
                response = _generate(prompt, base64_img)
                results = req["parse_fn"](response)
                return {"task": req["task"], "result": results}

        # 统一线程池，最大化 vLLM 连续批处理效率
        # 可通过环境变量 POPO_MAX_WORKERS 控制并发度
        import os as _os
        env_workers = int(_os.environ.get("POPO_MAX_WORKERS", "4"))
        max_workers = min(len(all_requests), env_workers)
        logger.info("扁平化并行: %d 个请求, %d workers", len(all_requests), max_workers)

        contd_pairs = []
        title_levels = []
        image_pairs = []
        merge_pairs = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_execute_request, req): req for req in all_requests}
            for future in as_completed(futures):
                ret = future.result()
                task = ret["task"]
                result = ret["result"]
                if task == "contd" and result:
                    contd_pairs.extend(result)
                elif task == "title" and result:
                    title_levels.extend(result)
                elif task == "image" and result:
                    image_pairs.extend(result)
                elif task == "table_merge" and result:
                    merge_pairs.append(result)

        # 回写结果
        for p in contd_pairs:
            src, tgt = p["src_id"], p["tgt_id"]
            if 1 <= src <= len(doc_blocks):
                doc_blocks[src - 1]["contd"] = tgt

        for lv in title_levels:
            bid = lv["id"]
            if 1 <= bid <= len(doc_blocks):
                doc_blocks[bid - 1]["level"] = lv["level"]

        for p in image_pairs:
            src, tgt = p["src_id"], p["tgt_id"]
            if 1 <= src <= len(doc_blocks):
                doc_blocks[src - 1]["image"] = tgt

        for t1_idx, t2_idx in merge_pairs:
            doc_blocks[t1_idx]["table_merge"] = t2_idx

        # 4. 保存中间产物
        if output_dir:
            import json
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            doc_stem = Path(pdf_path).stem
            out_path = output_dir / f"{doc_stem}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(doc_blocks, f, ensure_ascii=False, indent=2)
            logger.info("推理结果已保存: %s", out_path)

        # 统计
        contd_count = sum(1 for b in doc_blocks if b["contd"] > 0)
        title_count = sum(1 for b in doc_blocks if b["level"] >= 0)
        image_count = sum(1 for b in doc_blocks if b["image"] > 0)
        merge_count = sum(1 for b in doc_blocks if b["table_merge"] >= 0)
        logger.info(
            "Popo 推理完成: contd=%d, title=%d, image=%d, table_merge=%d",
            contd_count, title_count, image_count, merge_count,
        )

        return doc_blocks

    @staticmethod
    def _run_task(
        pdf_path: str,
        judge_blocks: list[dict],
        build_prompt_fn,
        parse_fn,
        task_name: str,
        chunk_size: int | None = None,
    ) -> list[dict]:
        """执行单个任务（分块 + 并行推理 + 响应解析）。

        所有 chunk 并行提交给 vLLM，利用连续批处理加速。

        Args:
            pdf_path: PDF 路径。
            judge_blocks: 过滤后的候选块。
            build_prompt_fn: prompt 构造函数。
            parse_fn: 响应解析函数。
            task_name: 任务名（日志用）。
            chunk_size: 自定义分块大小（None 用默认 _CHUNK_SIZE）。

        Returns:
            解析后的结果列表。
        """
        if not judge_blocks:
            return []

        # 动态分块
        chunks = _adaptive_chunk(judge_blocks, chunk_size=chunk_size) if chunk_size else _adaptive_chunk(judge_blocks)
        logger.info("[%s] %d 个候选块，分为 %d chunk", task_name, len(judge_blocks), len(chunks))

        # 并行推理所有 chunk
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _process_chunk(i_chunk):
            i, chunk = i_chunk
            pages = sorted(set(b["page"] for b in chunk))
            base64_img = _render_pages_to_image(pdf_path, pages)
            prompt = build_prompt_fn(chunk)
            logger.info("[%s] chunk %d/%d: %d 块, %d 页", task_name, i + 1, len(chunks), len(chunk), len(pages))
            response = _generate(prompt, base64_img)
            results = parse_fn(response)
            logger.info("[%s] chunk %d 解析出 %d 条结果", task_name, i + 1, len(results))
            return results

        all_results = []
        with ThreadPoolExecutor(max_workers=min(len(chunks), 16)) as executor:
            futures = {executor.submit(_process_chunk, (i, chunk)): i for i, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                all_results.extend(future.result())

        return all_results


# 模块级单例
popo_inference = PopoInference()
