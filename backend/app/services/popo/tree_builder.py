"""文档树构建器。

将 Popo 推理输出的扁平 doc_blocks 列表构建为嵌套文档树。

doc_blocks 中每个 block 含以下后处理字段：
- ``level``: 标题层级（-1=非标题，>0=标题层级）
- ``contd``: 文本截断关联（-1=无，>0=关联目标 block 的 id）
- ``image``: 图片关联（-1=无，>0=关联目标 block 的 id）
- ``table_merge``: 表格合并（-1=无，>=0=关联目标 block 的 idx）

构建规则：
1. ``level > 0`` 为标题节点，按层级嵌套（栈式构建）
2. ``level = -1`` 为内容节点，挂到栈顶标题
3. ``contd > 0`` 表示该块是截断前段，内容拼接到目标块，前段跳过
4. ``image > 0`` 表示该块关联到某图片，渲染时挂到对应图片下
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_tree(doc_blocks: list[dict]) -> dict:
    """构建嵌套文档树。

    Args:
        doc_blocks: Popo 推理输出的扁平 block 列表。

    Returns:
        文档树根节点::

            {
                "type": "root",
                "level": 0,
                "children": [
                    {
                        "type": "title",
                        "content": "章节标题",
                        "level": 1,
                        "page": 1,
                        "children": [...]
                    },
                    ...
                ]
            }
    """
    # 1. 构建 id → block 索引（id 从 1 开始）
    id_map = {b["id"]: b for b in doc_blocks if "id" in b}

    # 2. 处理 contd：将截断前段内容拼接到目标块
    skip_ids: set[int] = set()
    for block in doc_blocks:
        contd = block.get("contd", -1)
        if contd > 0 and contd in id_map:
            tgt = id_map[contd]
            tgt["content"] = block["content"] + tgt["content"]
            skip_ids.add(block["id"])

    # 3. 栈式构建文档树
    root = {"type": "root", "level": 0, "content": "", "children": []}
    stack = [root]

    for block in doc_blocks:
        bid = block.get("id", 0)
        if bid in skip_ids:
            continue

        level = block.get("level", -1)
        node = {
            "type": block["type"],
            "content": block["content"],
            "level": max(level, 0),
            "page": block.get("page", 0),
            "children": [],
        }

        if level > 0:
            # 标题节点：弹出栈中 >= 当前层级的节点
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            # 内容节点：挂到栈顶
            stack[-1]["children"].append(node)

    # 统计
    title_count = sum(1 for b in doc_blocks if b.get("level", -1) > 0)
    contd_count = len(skip_ids)
    logger.info("文档树构建完成: 标题=%d, 跨页合并=%d", title_count, contd_count)

    return root


def count_nodes(tree: dict) -> dict:
    """统计文档树节点数。

    Args:
        tree: 文档树根节点。

    Returns:
        统计字典：``{"titles": N, "texts": N, "tables": N, "images": N, "captions": N}``
    """
    counts = {"titles": 0, "texts": 0, "tables": 0, "images": 0, "captions": 0}

    def _count(node):
        for child in node.get("children", []):
            t = child["type"]
            if t == "title" or child["level"] > 0:
                counts["titles"] += 1
            elif t == "table":
                counts["tables"] += 1
            elif t in ("image", "seal"):
                counts["images"] += 1
            elif "caption" in t:
                counts["captions"] += 1
            else:
                counts["texts"] += 1
            _count(child)

    _count(tree)
    return counts
