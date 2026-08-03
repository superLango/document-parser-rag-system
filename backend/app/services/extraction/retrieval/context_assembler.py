"""上下文拼接器（Phase 3）。

将检索到的 ``RetrievedChunk`` 列表拼接为完整的上下文文本，供 Phase 4 LLM 抽取。

处理流程：
1. **子块 content 直接使用**：召回的子块 content 已经过表格增强（题注前置+自然语言描述），
   直接使用 content 而非 parent_text，避免父块中无关内容占据 token 预算。
2. **去重**：按 chunk_id 去重（同一子块只保留一次），同章节不同子块都保留。
3. **按 hierarchy_path 分组**：同章节内容连续排列
4. **表格块保留 HTML**：原始表格结构对 LLM 抽取重要
5. **token 控制**：上下文不超过 CONTEXT_MAX_TOKENS（默认 28000）

token 估算：中文约 1.5 字符/token，使用保守的 1.5 估算。
char_limit = token_limit * 1.5 = 28000 * 1.5 = 42000 字符

使用示例::

    from app.services.extraction.retrieval.context_assembler import context_assembler

    text = context_assembler.assemble(chunks, max_tokens=28000)
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import RetrievedChunk

logger = get_logger(__name__)

# 中文 token 估算系数：约 1.5 字符/token（保守估计）
_CHARS_PER_TOKEN = 1.5


class ContextAssembler:
    """上下文拼接器。

    将检索块列表拼接为 LLM 可用的上下文文本。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    def assemble(
        self,
        chunks: list[RetrievedChunk],
        max_tokens: int | None = None,
    ) -> str:
        """将检索块拼接为上下文文本。

        Args:
            chunks: 检索块列表（已按相关性排序）。
            max_tokens: 上下文最大 token 数，None 时使用配置项。

        Returns:
            str: 拼接后的上下文文本。
        """
        _max_tokens = max_tokens or self._settings.context_max_tokens
        char_limit = int(_max_tokens * _CHARS_PER_TOKEN)

        if not chunks:
            return ""

        # 1. 按 chunk_id 去重（同子块只保留一次，同章节不同子块都保留）
        deduped = self._dedup_by_chunk_id(chunks)

        # 2. 按 hierarchy_path 分组（保持相关性顺序）
        grouped = self._group_by_path(deduped)

        # 3. 拼接文本，控制 token 上限
        parts: list[str] = []
        total_chars = 0
        used_paths: set[str] = set()

        for chunk in grouped:
            # 直接使用子块 content（已表格增强：题注前置+自然语言描述）
            text = chunk.content
            if not text:
                continue

            # 标记章节分隔（可选，帮助 LLM 理解结构）
            section_prefix = ""
            if chunk.hierarchy_path and chunk.hierarchy_path not in used_paths:
                used_paths.add(chunk.hierarchy_path)
                section_prefix = f"\n\n--- {chunk.hierarchy_path} ---\n"

            chunk_text = section_prefix + text if section_prefix else text

            # token 控制
            if total_chars + len(chunk_text) > char_limit:
                # 截断最后一个块以填满剩余空间
                remaining = char_limit - total_chars
                if remaining > 200:  # 至少保留 200 字符才有价值
                    chunk_text = chunk_text[:remaining] + "\n[...内容截断...]"
                    parts.append(chunk_text)
                    total_chars += len(chunk_text)
                break

            parts.append(chunk_text)
            total_chars += len(chunk_text)

        context = "\n\n".join(parts)

        logger.info(
            "上下文拼接完成",
            extra={
                "input_chunks": len(chunks),
                "deduped_chunks": len(deduped),
                "context_chars": len(context),
                "estimated_tokens": int(len(context) / _CHARS_PER_TOKEN),
                "max_tokens": _max_tokens,
            },
        )
        return context

    def _dedup_by_chunk_id(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """按 chunk_id 去重。

        去重规则：相同 chunk_id 的子块只保留 score 最高的一个。
        同章节不同子块都保留（不再按 hierarchy_path 合并），
        避免父块无关内容占据 token 预算导致关键表格被截断。

        Args:
            chunks: 检索块列表。

        Returns:
            list[RetrievedChunk]: 去重后的块列表。
        """
        seen: dict[str, RetrievedChunk] = {}
        result: list[RetrievedChunk] = []

        for chunk in chunks:
            cid = chunk.chunk_id or chunk.hierarchy_path or ""

            if cid in seen:
                # 已有相同 chunk_id 的块，保留 score 更高的
                if chunk.score > seen[cid].score:
                    idx = next(
                        i for i, c in enumerate(result) if c is seen[cid]
                    )
                    result[idx] = chunk
                    seen[cid] = chunk
                continue

            seen[cid] = chunk
            result.append(chunk)

        return result

    @staticmethod
    def _group_by_path(
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """按 hierarchy_path 分组排列（同章节内容连续）。

        保持相关性顺序，但将相同 path 的块连续排列。

        Args:
            chunks: 去重后的块列表。

        Returns:
            list[RetrievedChunk]: 重新排列后的块列表。
        """
        # 已去重，每个 path 只有一个块，直接返回
        # 但按 path 分组排序：相同父路径的块连续
        path_order: dict[str, int] = {}
        ordered: list[RetrievedChunk] = []

        for chunk in chunks:
            path = chunk.hierarchy_path or ""
            # 提取父路径（去掉最后一段）
            parent_path = " > ".join(path.split(" > ")[:-1]) if " > " in path else path

            if parent_path not in path_order:
                path_order[parent_path] = len(ordered)
                ordered.append(chunk)
            else:
                # 插入到相同父路径的块后面
                insert_idx = path_order[parent_path] + 1
                ordered.insert(insert_idx, chunk)
                # 更新后续 path_order（因为 insert 改变了索引）
                for k in path_order:
                    if path_order[k] >= insert_idx:
                        path_order[k] += 1

        return ordered


# 模块级单例
context_assembler = ContextAssembler()
