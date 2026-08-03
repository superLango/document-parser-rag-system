"""层级化父子块切分器（核心新逻辑）。

切分原则：
- **语义完整性**：以段落、句子边界切分，禁止在句子或表格内部截断
- **层级继承**：子块继承父级的 hierarchy_path 和 title
- **大小控制**：单个子块不超过 embedding 模型窗口（默认 2000 字符）

流程：
1. 按 hierarchy_path 分组 → 每组为一个 ParentChunk（完整章节）
2. 对每个 ParentChunk：
   - content 字数超过阈值 → 按段落/句子边界切分为多个 ChildChunk
   - 否则 → 整体作为一个 ChildChunk
3. 所有 ChildChunk 继承父级的 hierarchy_path, title
4. 每个 ChildChunk 携带 parent_text（父块完整原文，召回后替换子块用）
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict

from app.services.vector.vector_models import ChildChunk, DocumentElement, ParentChunk
from app.services.vector.table_cleaner import table_cleaner
from app.services.vector.table_enhancer import table_enhancer

logger = logging.getLogger(__name__)

# 子块最大字符数（bge-m3 max_length=8192，留余量）
MAX_CHILD_CHARS = 2000

# overlap最大字符数
MAX_OVERLAP_CHARS = 200
# overlap最大句子数
MAX_OVERLAP_SENTENCES = 2
# overlap标记
OVERLAP_MARKER = "[--上下文接续--]"

# 段落/句子切分优先级
_PARA_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", "；", ";", "，", ","]

# 句子结束正则（中英文标点）
_SENTENCE_END_RE = re.compile(r"[。！？.!?；;]+")


class HierarchyChunker:
    """层级化父子块切分器。

    将层级重建后的 ``DocumentElement`` 列表切分为 ``ParentChunk`` + ``ChildChunk``。
    父块不存向量（仅作 parent_text），子块生成五维向量入库。

    Args:
        max_child_chars: 子块最大字符数。
    """

    def __init__(self, max_child_chars: int = MAX_CHILD_CHARS) -> None:
        self.max_child_chars = max_child_chars

    def chunk(
        self, elements: list[DocumentElement], doc_id: str
    ) -> tuple[list[ParentChunk], list[ChildChunk]]:
        """层级化切分流程。

        Args:
            elements: 层级重建后的 DocumentElement 列表。
            doc_id: 文档 ID（用于生成块 ID）。

        Returns:
            (parent_chunks, child_chunks) 元组。
        """
        if not elements:
            return [], []

        # 1. 按 hierarchy_path 分组（保持顺序）
        path_groups: OrderedDict[str, list[DocumentElement]] = OrderedDict()
        for elem in elements:
            path = elem.hierarchy_path or "文档根节点"
            if path not in path_groups:
                path_groups[path] = []
            path_groups[path].append(elem)

        # 2. 每组创建 ParentChunk + ChildChunk
        parent_chunks: list[ParentChunk] = []
        child_chunks: list[ChildChunk] = []
        parent_idx = 0

        for path, group_elements in path_groups.items():
            parent_id = f"{doc_id}_p{parent_idx}"
            parent = self._create_parent(parent_id, path, group_elements)
            parent_chunks.append(parent)

            # 切分子块
            children = self._create_children(parent, group_elements)
            child_chunks.extend(children)

            parent_idx += 1

        logger.info(
            "父子块切分完成",
            extra={
                "parent_count": len(parent_chunks),
                "child_count": len(child_chunks),
                "doc_id": doc_id,
            },
        )
        return parent_chunks, child_chunks

    # ------------------------------------------------------------------
    # 父块创建
    # ------------------------------------------------------------------

    @staticmethod
    def _create_parent(
        parent_id: str, path: str, elements: list[DocumentElement]
    ) -> ParentChunk:
        """创建父块。"""
        # 提取标题（第一个 title 元素或路径最后一段）
        title = ""
        for elem in elements:
            if elem.type == "title":
                title = elem.content.strip()
                break
        if not title:
            title = path.split(" > ")[-1] if path != "文档根节点" else "文档根节点"

        # 拼接父块完整内容
        content_parts: list[str] = []
        source_pages: list[int] = []
        has_table = False
        level = 3
        for elem in elements:
            content_parts.append(elem.content)
            if elem.page_num not in source_pages:
                source_pages.append(elem.page_num)
            if elem.type == "table":
                has_table = True
            if elem.type == "title" and elem.hierarchy_level < level:
                level = elem.hierarchy_level

        return ParentChunk(
            id=parent_id,
            hierarchy_path=path,
            title=title[:512],
            level=level,
            content="\n".join(content_parts),
            parent_path=None,
            source_pages=source_pages,
            has_table=has_table,
            semantic_label="",
        )

    # ------------------------------------------------------------------
    # 子块创建
    # ------------------------------------------------------------------

    def _create_children(
        self, parent: ParentChunk, elements: list[DocumentElement]
    ) -> list[ChildChunk]:
        """为父块创建子块。

        流程：
        1. 收集父块内所有元素内容（表格前置题注，使 content_vector 捕获题注语义）
        2. 判断总字数是否超过阈值
        3. 超过 → 按段落/句子边界切分
        4. 未超过 → 整体作为一个子块
        """
        # 提取父块原始内容（按元素粒度）
        # 表格元素进行双重增强：题注前置 + 表格内容增强（自然语言描述）
        # 使 content_vector 编码时捕获题注语义和表格数据语义，提升检索召回率
        contents: list[tuple[str, bool, list[int]]] = []  # (content, has_table, pages)
        for elem in elements:
            has_table = elem.type == "table"
            pages = [elem.page_num]
            content = elem.content
            if has_table:
                caption = getattr(elem, "caption", "") or ""
                table_num = getattr(elem, "table_num", "") or ""
                # 1. 题注前置：用户查询 "表3 化学成分" 即可通过题注召回对应表格
                if caption:
                    content = f"【{table_num} {caption}】\n\n{content}"
                # 2. 表格内容增强：生成自然语言描述（概述+逐行+列统计）前置，
                #    使 content_vector 捕获表格数据语义，提升数值型查询的召回率
                enhanced = table_enhancer.enhance(elem.content, caption=caption)
                if enhanced:
                    content = f"{enhanced}\n\n{content}"
            contents.append((content, has_table, pages))

        total_chars = sum(len(c) for c, _, _ in contents)

        if total_chars <= self.max_child_chars:
            # 整体作为一个子块
            return [
                self._make_child(
                    parent=parent,
                    chunk_index=0,
                    content="\n".join(c for c, _, _ in contents),
                    has_table=any(ht for _, ht, _ in contents),
                    source_pages=parent.source_pages,
                )
            ]

        # 需要切分
        return self._split_into_children(parent, contents)

    def _split_into_children(
        self,
        parent: ParentChunk,
        contents: list[tuple[str, bool, list[int]]],
    ) -> list[ChildChunk]:
        """按段落/句子边界切分为多个子块，支持相邻块overlap。"""
        # 展开为（文本片段, has_table, page）列表
        segments: list[tuple[str, bool, int]] = []
        for content, has_table, pages in contents:
            if table_cleaner.is_table(content):
                # 表格不切分，作为独立段
                segments.append((content, True, pages[0]))
            else:
                # 文本按段落/句子切分
                for seg in self._split_text(content):
                    if seg.strip():
                        segments.append((seg, has_table, pages[0]))

        # 贪心合并：在 max_child_chars 限制内合并段，加入overlap
        children: list[ChildChunk] = []
        current_parts: list[str] = []
        current_chars = 0
        current_has_table = False
        current_pages: list[int] = []
        chunk_idx = 0
        prev_tail = ""  # 上一个chunk的尾部overlap文本
        prev_was_table = False  # 上一个chunk是否是表格块（表格不参与overlap）

        def _flush_current():
            nonlocal chunk_idx, current_parts, current_chars, current_has_table, current_pages, prev_tail, prev_was_table
            if not current_parts:
                return
            content = "\n".join(current_parts)
            is_table_chunk = current_has_table
            # 添加overlap前缀（首块无前缀，表格块不加前缀，上一块是表格也不加）
            if prev_tail and not is_table_chunk and not prev_was_table:
                content = prev_tail + "\n" + OVERLAP_MARKER + "\n" + content
            # 创建子块
            children.append(
                self._make_child(
                    parent, chunk_idx,
                    content,
                    current_has_table,
                    current_pages,
                )
            )
            # 提取当前chunk的尾部overlap（仅非表格块）
            if not is_table_chunk:
                # 移除可能的overlap前缀再提取尾部
                plain_content = content
                if OVERLAP_MARKER in plain_content:
                    plain_content = plain_content.split(OVERLAP_MARKER, 1)[-1].strip()
                prev_tail = self._extract_tail_sentences(plain_content, MAX_OVERLAP_CHARS, MAX_OVERLAP_SENTENCES)
            else:
                prev_tail = ""  # 表格块不向后传递overlap
            prev_was_table = is_table_chunk
            chunk_idx += 1
            current_parts = []
            current_chars = 0
            current_has_table = False
            current_pages = []

        for seg_text, seg_has_table, seg_page in segments:
            seg_len = len(seg_text)

            # 如果当前段是表格，先flush当前缓冲，再单独处理表格
            if seg_has_table and current_parts:
                _flush_current()

            # 如果当前段本身超过阈值，先flush缓冲，再单独作为一个子块
            if seg_len >= self.max_child_chars:
                if current_parts:
                    _flush_current()
                # 超长段单独成块
                current_parts.append(seg_text)
                current_chars = seg_len
                current_has_table = seg_has_table
                if seg_page not in current_pages:
                    current_pages.append(seg_page)
                _flush_current()
                continue

            # 判断是否可以加入当前缓冲（考虑overlap占用的空间）
            overlap_reserve = len(prev_tail) + len(OVERLAP_MARKER) + 2 if (prev_tail and not prev_was_table and not seg_has_table) else 0
            if current_chars + seg_len + 1 + overlap_reserve > self.max_child_chars and current_parts:
                _flush_current()

            # 加入缓冲
            current_parts.append(seg_text)
            current_chars += seg_len + 1
            if seg_has_table:
                current_has_table = True
            if seg_page not in current_pages:
                current_pages.append(seg_page)

            # 表格段单独flush
            if seg_has_table:
                _flush_current()

        # 刷新最后缓冲
        if current_parts:
            _flush_current()

        return children

    @staticmethod
    def _extract_tail_sentences(text: str, max_chars: int, max_sentences: int) -> str:
        """从文本尾部提取最后1-2个完整句子作为overlap。

        从文本末尾向前查找句子结束标点，提取最后N个完整句子，
        不超过max_chars字符数。
        """
        if not text or not text.strip():
            return ""
        text = text.strip()
        # 从末尾向前查找句子结束位置
        end_positions = []
        for m in _SENTENCE_END_RE.finditer(text):
            end_positions.append(m.end())
        if not end_positions:
            # 没有明确句子结束，取末尾max_chars字符（但不超过文本30%）
            take = min(max_chars, len(text) // 3)
            if take < 10:
                return ""
            tail = text[-take:].strip()
            # 尝试从最近的空格/换行截断
            for sep in [" ", "\n", "\t"]:
                idx = tail.find(sep)
                if idx > 0:
                    tail = tail[idx:].strip()
                    break
            return tail
        # 取最后max_sentences个句子结束位置
        take_ends = end_positions[-max_sentences:]
        start_pos = take_ends[0]
        # 向前找句子起始位置（跳过标点和空白）
        while start_pos > 0 and text[start_pos - 1] in "。！？.!?；; \n\t":
            start_pos -= 1
        # 再向前跳过空白
        while start_pos > 0 and text[start_pos - 1] in " \n\t":
            start_pos -= 1
        # 找前一个句子结束位置作为起点
        prev_ends = [e for e in end_positions if e < start_pos]
        if prev_ends:
            start_pos = prev_ends[-1]
        else:
            start_pos = 0
        tail = text[start_pos:].strip()
        # 长度限制
        if len(tail) > max_chars:
            tail = tail[-max_chars:].strip()
            # 从最近的句子结束点截断
            for m in list(_SENTENCE_END_RE.finditer(tail))[1:]:
                tail = tail[m.end():].strip()
                if len(tail) <= max_chars:
                    break
        return tail if len(tail) >= 10 else ""

    @staticmethod
    def _make_child(
        parent: ParentChunk,
        chunk_index: int,
        content: str,
        has_table: bool,
        source_pages: list[int],
    ) -> ChildChunk:
        """创建单个子块。"""
        return ChildChunk(
            id=f"{parent.id}_{chunk_index}",
            parent_id=parent.id,
            hierarchy_path=parent.hierarchy_path,
            title=parent.title,
            content=content,
            parent_text=parent.content,  # 携带父块完整原文
            chunk_index=chunk_index,
            level=parent.level,
            has_table=has_table,
            semantic_label=parent.semantic_label,
            source_pages=source_pages,
        )

    # ------------------------------------------------------------------
    # 文本切分
    # ------------------------------------------------------------------

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """按段落/句子边界切分文本。

        优先级：``\\n\\n``（段落）> ``\\n``（换行）> 句号 > 分号 > 逗号

        禁止在句子内部截断。
        """
        if not text or not text.strip():
            return []

        # 先按段落切分
        paragraphs = re.split(r"\n\s*\n", text)
        if len(paragraphs) > 1:
            return [p.strip() for p in paragraphs if p.strip()]

        # 单段落：按换行切分
        lines = text.split("\n")
        if len(lines) > 1:
            return [l.strip() for l in lines if l.strip()]

        # 单行：按句号切分
        sentences = re.split(r"(?<=[。！？.!?；;])", text)
        return [s.strip() for s in sentences if s.strip()]


# 模块级单例
hierarchy_chunker = HierarchyChunker()
