"""层级父子分块器（S2/D1，消费 layout.json v1.2）。

流程：
1. 从 layout.rebuild.document_tree 深度遍历生成 DocumentElement 列表
   （层级面包屑由标题节点栈式计算，块类型对齐 parsekit BLOCK_TYPES）；
2. 按 hierarchy_path 分组 → ParentChunk（完整章节，作 parent_text）；
3. 组内切分子块：文本按段落/句子边界切分（禁止句子内截断），
   表格独立成块不切分；子块携带 overlap 与 content_for_embedding；
4. 无 document_tree 时降级为单父块顺序切分（不崩溃，记日志）。

与旧项目 chunker.py 的关系：沿用"层级继承/表格不切分/overlap/parent_text"
设计思想，但输入契约、块类型集合、表格增强文本流向、chunk_id 格式均按
当前项目重构；不依赖 Popo merged.json 与旧 DocumentElement 构造。
"""

from __future__ import annotations

import re
from collections import OrderedDict

from app.core.logging import get_logger

from .models import ChildChunk, DocumentElement, ParentChunk
from .table_enhancer import table_enhancer

logger = get_logger(__name__)

# 子块最大字符数（BGE-M3 max_length=8192 留余量；表格增强文本计入）
MAX_CHILD_CHARS = 2000
# overlap 最大字符数 / 最大句子数
MAX_OVERLAP_CHARS = 200
MAX_OVERLAP_SENTENCES = 2
OVERLAP_MARKER = "[--上下文接续--]"

# 文档树最大深度（防恶意/异常 layout.json 导致递归过深）
MAX_TREE_DEPTH = 32

# 文本类型（参与正文分块）
_TEXT_TYPES = frozenset(
    {"text", "list_item", "footnote", "aside_text", "formula", "page_title"}
)
# 标题类型
_TITLE_TYPES = frozenset({"title"})
# 表格类型
_TABLE_TYPES = frozenset({"table"})
# 跳过类型（图片与题注由树结构承载，不独立成文本块）
_SKIP_TYPES = frozenset({"image", "image_caption", "table_caption"})

# 句子结束正则（中英文标点）
_SENTENCE_END_RE = re.compile(r"[。！？.!?；;]+")

# 表格编号提取（"表3 化学成分" → "表3"）
_TABLE_NUM_RE = re.compile(r"表\s*[0-9]+")


class HierarchyChunker:
    """层级父子分块器。"""

    def __init__(
        self,
        max_child_chars: int = MAX_CHILD_CHARS,
        max_overlap_chars: int = MAX_OVERLAP_CHARS,
        max_overlap_sentences: int = MAX_OVERLAP_SENTENCES,
        max_tree_depth: int = MAX_TREE_DEPTH,
    ) -> None:
        self.max_child_chars = max_child_chars
        self.max_overlap_chars = max_overlap_chars
        self.max_overlap_sentences = max_overlap_sentences
        self.max_tree_depth = max_tree_depth

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def chunk(
        self, layout: dict, doc_id: str
    ) -> tuple[list[ParentChunk], list[ChildChunk]]:
        """执行分块。

        Args:
            layout: layout.json v1.2 解析结果。
            doc_id: 文档 ID（用于生成块 ID）。

        Returns:
            (parent_chunks, child_chunks)。
        """
        elements = self._elements_from_layout(layout)
        if not elements:
            return [], []

        # 按层级路径分组（保持阅读顺序）
        path_groups: OrderedDict[str, list[DocumentElement]] = OrderedDict()
        for elem in elements:
            path = elem.hierarchy_path or "文档根节点"
            path_groups.setdefault(path, []).append(elem)

        parents: list[ParentChunk] = []
        children: list[ChildChunk] = []
        for parent_idx, (path, group) in enumerate(path_groups.items()):
            parent_id = f"{doc_id}_p{parent_idx}"
            parent = self._create_parent(parent_id, path, group)
            parents.append(parent)
            children.extend(self._create_children(parent, group))

        logger.info(
            "层级父子分块完成",
            doc_id=doc_id,
            parent_count=len(parents),
            child_count=len(children),
            group_count=len(path_groups),
        )
        return parents, children

    # ------------------------------------------------------------------
    # layout.json → DocumentElement
    # ------------------------------------------------------------------

    def _elements_from_layout(self, layout: dict) -> list[DocumentElement]:
        """从 layout.json 提取分块元素（优先 document_tree，降级 pages.blocks）。"""
        rebuild = layout.get("rebuild") or {}
        tree = rebuild.get("document_tree") or {}
        if tree.get("children"):
            return self._elements_from_tree(tree)
        # 降级：按 pages.blocks 顺序构造根父块
        logger.warning(
            "document_tree 缺失或为空，降级按 blocks 顺序分块",
            page_count=layout.get("page_count", 0),
        )
        return self._elements_from_blocks(layout)

    def _elements_from_tree(self, tree: dict) -> list[DocumentElement]:
        """深度遍历 document_tree 生成元素（面包屑栈式维护）。"""
        elements: list[DocumentElement] = []
        breadcrumbs: list[str] = []

        def walk(node: dict, depth: int) -> None:
            if depth > self.max_tree_depth:
                logger.warning("document_tree 深度超过上限，截断", depth=depth)
                return
            node_type = node.get("type", "")
            content = (node.get("content") or "").strip()
            page = int(node.get("page") or 0)
            order = int(node.get("order") or 0)
            level = int(node.get("level") or 0)

            if node_type in _TITLE_TYPES:
                title = content or "未命名标题"
                if not breadcrumbs or breadcrumbs[-1] != title:
                    breadcrumbs.append(title)
                elements.append(
                    DocumentElement(
                        type=node_type,
                        content=content,
                        page=page,
                        order=order,
                        hierarchy_path=" > ".join(breadcrumbs),
                        title=title,
                        level=level,
                    )
                )
            elif node_type in _TABLE_TYPES:
                caption, table_num = self._extract_caption(node)
                elements.append(
                    DocumentElement(
                        type="table",
                        content=content,
                        page=page,
                        order=order,
                        hierarchy_path=" > ".join(breadcrumbs) or "文档根节点",
                        title=breadcrumbs[-1] if breadcrumbs else "",
                        level=level,
                        has_table=True,
                        caption=caption,
                        table_num=table_num,
                    )
                )
            elif node_type in _TEXT_TYPES:
                if content:
                    elements.append(
                        DocumentElement(
                            type=node_type,
                            content=content,
                            page=page,
                            order=order,
                            hierarchy_path=" > ".join(breadcrumbs) or "文档根节点",
                            title=breadcrumbs[-1] if breadcrumbs else "",
                            level=level,
                        )
                    )
            # image/image_caption/table_caption 不独立成块（caption 已挂表格）

            for child in node.get("children") or []:
                walk(child, depth + 1)

            if node_type in _TITLE_TYPES and breadcrumbs:
                breadcrumbs.pop()

        walk(tree, 0)
        return elements

    @staticmethod
    def _extract_caption(table_node: dict) -> tuple[str, str]:
        """从表格节点子节点提取题注与编号。"""
        caption = ""
        for child in table_node.get("children") or []:
            if child.get("type") == "table_caption":
                caption = (child.get("content") or "").strip()
                break
        match = _TABLE_NUM_RE.search(caption)
        table_num = match.group(0) if match else ""
        return caption, table_num

    def _elements_from_blocks(self, layout: dict) -> list[DocumentElement]:
        """降级路径：无 document_tree 时按 pages.blocks 顺序构造元素。"""
        elements: list[DocumentElement] = []
        for page in layout.get("pages") or []:
            page_index = int(page.get("page_index") or 0)
            for block in page.get("blocks") or []:
                btype = block.get("type", "")
                content = (block.get("content") or "").strip()
                if not content or btype in _SKIP_TYPES:
                    continue
                elements.append(
                    DocumentElement(
                        type=btype,
                        content=content,
                        page=page_index,
                        order=int(block.get("order") or 0),
                        hierarchy_path="文档根节点",
                        title="",
                        has_table=btype in _TABLE_TYPES,
                        source=block.get("source") or "rule",
                    )
                )
        return elements

    # ------------------------------------------------------------------
    # 父块
    # ------------------------------------------------------------------

    @staticmethod
    def _create_parent(
        parent_id: str, path: str, elements: list[DocumentElement]
    ) -> ParentChunk:
        """创建父块（完整章节）。"""
        title = ""
        level = 0
        has_table = False
        source_pages: list[int] = []
        for elem in elements:
            if elem.type in _TITLE_TYPES and not title:
                title = elem.content.strip()
            if elem.has_table:
                has_table = True
            if elem.level and (level == 0 or elem.level < level):
                level = elem.level
            if elem.page not in source_pages:
                source_pages.append(elem.page)
        if not title:
            title = path.split(" > ")[-1] if path != "文档根节点" else "文档根节点"

        return ParentChunk(
            id=parent_id,
            hierarchy_path=path,
            title=title[:512],
            level=level,
            content="\n".join(e.content for e in elements),
            source_pages=source_pages,
            has_table=has_table,
            semantic_label="",
        )

    # ------------------------------------------------------------------
    # 子块
    # ------------------------------------------------------------------

    def _create_children(
        self, parent: ParentChunk, elements: list[DocumentElement]
    ) -> list[ChildChunk]:
        """为父块创建子块（表格独立、文本边界切分、overlap）。"""
        contents: list[tuple[str, str, bool, int]] = []  # (embed, raw, has_table, page)
        for elem in elements:
            if elem.has_table:
                raw = elem.content
                enhanced = table_enhancer.enhance(raw, caption=elem.caption)
                embed = elem.content
                if elem.caption:
                    # caption 已含编号（如 "表1 化学成分"），直接整体前置避免编号重复
                    embed = f"【{elem.caption}】\n\n{embed}"
                if enhanced:
                    embed = f"{enhanced}\n\n{embed}"
                contents.append((embed, raw, True, elem.page))
            else:
                contents.append((elem.content, elem.content, False, elem.page))

        total_chars = sum(len(embed) for embed, _, _, _ in contents)
        if total_chars <= self.max_child_chars:
            return [
                self._make_child(
                    parent=parent,
                    chunk_index=0,
                    content="\n".join(raw for _, raw, _, _ in contents),
                    content_for_embedding="\n".join(embed for embed, _, _, _ in contents),
                    has_table=any(ht for _, _, ht, _ in contents),
                    source_pages=parent.source_pages,
                )
            ]
        return self._split_into_children(parent, contents)

    def _split_into_children(
        self, parent: ParentChunk, contents: list[tuple[str, str, bool, int]]
    ) -> list[ChildChunk]:
        """按段落/句子边界切分，支持相邻块 overlap。"""
        segments: list[tuple[str, str, bool, int]] = []
        for embed, raw, has_table, page in contents:
            if has_table:
                segments.append((embed, raw, True, page))
            else:
                for seg in self._split_text(embed):
                    if seg.strip():
                        segments.append((seg, seg, False, page))

        children: list[ChildChunk] = []
        current: list[tuple[str, str, bool, int]] = []
        current_chars = 0
        chunk_idx = 0
        prev_tail = ""
        prev_was_table = False

        def flush() -> None:
            nonlocal current, current_chars, chunk_idx, prev_tail, prev_was_table
            if not current:
                return
            raw_parts = [r for _, r, _, _ in current]
            embed_parts = [e for e, _, _, _ in current]
            pages = list(dict.fromkeys(p for _, _, _, p in current))
            content = "\n".join(raw_parts)
            embed = "\n".join(embed_parts)
            is_table_chunk = any(ht for _, _, ht, _ in current)
            # overlap 前缀（首块/表格块不添加）
            if prev_tail and not is_table_chunk and not prev_was_table:
                embed = f"{prev_tail}\n{OVERLAP_MARKER}\n{embed}"
            children.append(
                self._make_child(
                    parent=parent,
                    chunk_index=chunk_idx,
                    content=content,
                    content_for_embedding=embed,
                    has_table=is_table_chunk,
                    source_pages=pages,
                )
            )
            if not is_table_chunk:
                plain = embed.split(OVERLAP_MARKER, 1)[-1].strip()
                prev_tail = self._extract_tail_sentences(
                    plain, self.max_overlap_chars, self.max_overlap_sentences
                )
            else:
                prev_tail = ""
            prev_was_table = is_table_chunk
            chunk_idx += 1
            current = []
            current_chars = 0

        for seg_embed, seg_raw, seg_has_table, seg_page in segments:
            seg_len = len(seg_embed)
            if seg_has_table and current:
                flush()
            if seg_len >= self.max_child_chars and not seg_has_table:
                # 超长文本段：弱边界（逗号/顿号）优先，最终按阈值硬切，保证有界
                if current:
                    flush()
                for part in self._hard_split_segment(seg_embed, self.max_child_chars):
                    current.append((part, part, False, seg_page))
                    if current_chars + len(part) + 1 > self.max_child_chars:
                        flush()
                flush()
                continue
            overlap_reserve = (
                len(prev_tail) + len(OVERLAP_MARKER) + 2
                if prev_tail and not prev_was_table and not seg_has_table
                else 0
            )
            if current_chars + seg_len + 1 + overlap_reserve > self.max_child_chars and current:
                flush()
            current.append((seg_embed, seg_raw, seg_has_table, seg_page))
            current_chars += seg_len + 1
            if seg_has_table:
                flush()

        if current:
            flush()
        return children

    def _make_child(
        self,
        parent: ParentChunk,
        chunk_index: int,
        content: str,
        content_for_embedding: str,
        has_table: bool,
        source_pages: list[int],
    ) -> ChildChunk:
        """创建子块（tokens 先按字符数近似，S5 由 BM25 词元数接管）。"""
        return ChildChunk(
            chunk_id=f"{parent.id}_{chunk_index}",
            parent_chunk_id=parent.id,
            chunk_index=chunk_index,
            hierarchy_path=parent.hierarchy_path,
            title=parent.title,
            level=parent.level,
            has_table=has_table,
            semantic_label="table" if has_table else "text",
            source_pages=source_pages,
            content=content,
            content_for_embedding=content_for_embedding,
            parent_text=parent.content,
            tokens=len(content),
        )

    # ------------------------------------------------------------------
    # 文本切分与 overlap
    # ------------------------------------------------------------------

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """按优先级切分：段落 > 换行 > 句子（禁止句子内截断）。"""
        if not text or not text.strip():
            return []
        paragraphs = re.split(r"\n\s*\n", text)
        if len(paragraphs) > 1:
            return [p.strip() for p in paragraphs if p.strip()]
        lines = text.split("\n")
        if len(lines) > 1:
            return [ln.strip() for ln in lines if ln.strip()]
        sentences = re.split(r"(?<=[。！？.!?；;])", text)
        return [s.strip() for s in sentences if s.strip()]

    @staticmethod
    def _hard_split_segment(text: str, max_len: int = MAX_CHILD_CHARS) -> list[str]:
        """超长文本段切分：弱边界（逗号/分号/顿号）优先，最终按阈值硬切。

        用于无句子边界可用的长文本（如长列表、连续编码串），保证子块有界。
        """
        if len(text) <= max_len:
            return [text] if text else []
        parts: list[str] = []
        buf = ""
        for piece in re.split(r"(?<=[，,；;、])", text):
            if len(buf) + len(piece) <= max_len:
                buf += piece
            else:
                if buf:
                    parts.append(buf)
                buf = piece
                while len(buf) > max_len:
                    parts.append(buf[:max_len])
                    buf = buf[max_len:]
        if buf:
            parts.append(buf)
        return [p for p in parts if p.strip()]

    def _extract_tail_sentences(self, text: str, max_chars: int, max_sentences: int) -> str:
        """从文本尾部提取最后 N 个完整句子作为 overlap。

        规则：
        - 优先取尾部最后 max_sentences 个完整句子（向前扩展到句子开头）；
        - 超过 max_chars 时从头截断并尽量落在句子结束点；
        - 无句子边界时取末尾三分之一且不小于 10 字符。
        """
        if not text or not text.strip():
            return ""
        text = text.strip()
        ends = [m.end() for m in _SENTENCE_END_RE.finditer(text)]
        if not ends:
            take = min(max_chars, len(text) // 3)
            if take < 10:
                return ""
            tail = text[-take:].strip()
            for sep in (" ", "\n", "\t"):
                idx = tail.find(sep)
                if idx > 0:
                    tail = tail[idx:].strip()
                    break
            return tail
        # 起点：最后 max_sentences 个句子结束点，再向前扩展到句子开头
        start = ends[-max_sentences] if len(ends) >= max_sentences else ends[0]
        while start > 0 and text[start - 1] in "。！？.!?；; \n\t":
            start -= 1
        prev = [e for e in ends if e < start]
        if prev:
            start = prev[-1]
        else:
            start = 0
        tail = text[start:].strip()
        if len(tail) > max_chars:
            # 超长：从头截取 max_chars，尽量以句子结束点截断
            tail = tail[:max_chars]
            cuts = [m.end() for m in _SENTENCE_END_RE.finditer(tail)]
            for c in reversed(cuts):
                if c >= 10:
                    return tail[:c].strip()
        return tail if len(tail) >= 10 else ""


hierarchy_chunker = HierarchyChunker()
