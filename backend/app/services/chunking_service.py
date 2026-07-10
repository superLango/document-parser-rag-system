"""结构感知分块服务模块。

本模块按方案 8.1 节实现文档的结构感知分块能力，主要功能包括：

- 章节结构提取：通过正则匹配 "3.2.1 标题" 形式的编号章节标题，识别文档层级结构
- 标题层级链构建：基于章节编号深度维护层级栈，生成形如
  "文档 > 3 技术要求 > 3.2 材料 > 3.2.1 不锈钢" 的标题层级链
- 递归文本分块：使用 langchain 的 RecursiveCharacterTextSplitter 对每个章节内容
  进行递归分块，分隔符按中文语境优先级排列（段落 > 换行 > 句号 > 分号 > 逗号 > 空格）
- 按页分块支持：对 OCR 结果（每页含 text 字段）拼接后统一分块

使用示例：
    from app.services.chunking_service import chunker

    chunks = await chunker.chunk_document(text, {
        "doc_id": "doc-001",
        "doc_title": "采购技术规范",
        "file_name": "spec.pdf",
    })

分块输出格式：
    [
        {
            "chunk_id": "doc-001_3_2_1_0",
            "text": "...",
            "metadata": {
                "doc_id": "doc-001",
                "doc_title": "采购技术规范",
                "file_name": "spec.pdf",
                "title_chain": "采购技术规范 > 3 技术要求 > 3.2 材料 > 3.2.1 不锈钢",
                "section_level": "3.2.1",
                "section_title": "不锈钢",
                "chunk_index": 0
            }
        },
        ...
    ]
"""

import asyncio
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.logging import get_logger

logger = get_logger(__name__)

# 匹配 "3.2.1 标题" 形式的编号章节标题
# 编号由数字与点号组成，标题为编号后的非空文本
_SECTION_PATTERN: re.Pattern[str] = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

# 中文语境下的递归分块分隔符，按优先级从高到低排列
# 优先在段落边界切分，其次换行、句号、分号、逗号、空格，最后逐字符
_DEFAULT_SEPARATORS: list[str] = ["\n\n", "\n", "。", "；", "，", " ", ""]


class StructureAwareChunker:
    """结构感知分块器 - 按方案 8.1 节实现。

    使用 langchain RecursiveCharacterTextSplitter 进行递归分块，
    先提取章节结构，再对每个章节内容进行分块。每个分块携带完整的标题层级链
    与章节定位信息，便于后续向量检索时按章节过滤与上下文回溯。

    Attributes:
        _text_splitter: langchain 递归字符文本分块器实例。
        _chunk_size: 单个分块的最大字符数。
        _chunk_overlap: 相邻分块之间的重叠字符数，用于保持上下文连贯性。
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: list[str] | None = None,
    ) -> None:
        """初始化结构感知分块器。

        创建 langchain RecursiveCharacterTextSplitter 实例，配置中文分隔符。
        分块器本身为纯 CPU 计算且无副作用，可安全复用。

        Args:
            chunk_size: 单个分块的最大字符数，默认 512。
            chunk_overlap: 相邻分块之间的重叠字符数，默认 64。
            separators: 递归分块使用的分隔符列表，默认使用中文分隔符。
        """
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators or _DEFAULT_SEPARATORS,
            length_function=len,
        )

    async def chunk_document(self, text: str, doc_meta: dict) -> list[dict]:
        """将文档按章节结构分块。

        流程：
        1. 校验输入文本与元数据非空
        2. 提取章节结构（含标题层级链）
        3. 对每个章节内容调用 RecursiveCharacterTextSplitter 递归分块
        4. 为每个分块生成唯一 chunk_id 与完整元数据

        Args:
            text: 文档纯文本。
            doc_meta: 文档元数据，需包含 doc_id、doc_title、file_name。

        Returns:
            list[dict]: 分块列表，每个分块含 chunk_id、text 与 metadata 字段。
                文本为空或无有效内容时返回空列表。
        """
        # 校验输入文本
        if not text or not text.strip():
            logger.warning("分块输入文本为空", doc_id=doc_meta.get("doc_id"))
            return []

        # 校验 doc_id 存在，用于生成 chunk_id
        if not doc_meta.get("doc_id"):
            logger.warning("doc_meta 缺少 doc_id 字段", doc_meta=doc_meta)
            return []

        # 提取章节结构
        sections = self._extract_sections(text, doc_meta)
        logger.info(
            "章节结构提取完成",
            doc_id=doc_meta.get("doc_id"),
            section_count=len(sections),
        )

        chunks: list[dict] = []
        # 对每个章节递归分块
        for section in sections:
            content = section["content"]
            # 章节内容为空时跳过（仅产生无意义空分块）
            if not content.strip():
                continue

            # 通过 asyncio.to_thread 调用同步的 split_text，避免阻塞事件循环
            sub_chunks = await asyncio.to_thread(
                self._text_splitter.split_text, content
            )

            title_chain = " > ".join(section["title_hierarchy"])
            level_safe = section["level"].replace(".", "_")

            for idx, chunk_text in enumerate(sub_chunks):
                chunk_id = f"{doc_meta['doc_id']}_{level_safe}_{idx}"
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "metadata": {
                            "doc_id": doc_meta.get("doc_id"),
                            "doc_title": doc_meta.get("doc_title", ""),
                            "file_name": doc_meta.get("file_name", ""),
                            "title_chain": title_chain,
                            "section_level": section["level"],
                            "section_title": section["title"],
                            "chunk_index": idx,
                        },
                    }
                )

        logger.info(
            "文档分块完成",
            doc_id=doc_meta.get("doc_id"),
            section_count=len(sections),
            chunk_count=len(chunks),
        )
        return chunks

    def _extract_sections(self, text: str, doc_meta: dict) -> list[dict]:
        """提取章节结构，匹配 "3.2.1 标题" 格式。

        使用基于深度的层级栈维护标题层级关系：遇到新章节时，弹出栈中深度
        大于等于当前章节的项，保留其祖先章节，从而正确构建层级链。

        层级链格式示例：
            ["文档标题", "3 技术要求", "3.2 材料", "3.2.1 不锈钢"]

        对于文档开头无章节标题的内容，归入 level="0" 的前置章节。

        Args:
            text: 文档纯文本。
            doc_meta: 文档元数据，用于获取文档标题作为层级链根节点。

        Returns:
            list[dict]: 章节列表，每个章节含：
                - level: 章节编号，如 "3.2.1"
                - title: 章节标题文本
                - title_hierarchy: 标题层级链列表
                - content: 章节正文内容
        """
        doc_title = doc_meta.get("doc_title", "文档")
        lines = text.split("\n")
        sections: list[dict] = []
        # 层级栈，元素为 (深度, "level title")，用于维护当前章节的祖先链
        hierarchy_stack: list[tuple[int, str]] = []

        for line in lines:
            match = _SECTION_PATTERN.match(line.strip())
            if match:
                level = match.group(1)
                title = match.group(2).strip()
                depth = len(level.split("."))
                entry = f"{level} {title}"

                # 弹出栈中深度大于等于当前章节的项，仅保留祖先章节
                while hierarchy_stack and hierarchy_stack[-1][0] >= depth:
                    hierarchy_stack.pop()
                hierarchy_stack.append((depth, entry))

                # 构建标题层级链：文档标题 + 祖先章节
                title_hierarchy = [doc_title] + [e[1] for e in hierarchy_stack]

                sections.append(
                    {
                        "level": level,
                        "title": title,
                        "title_hierarchy": title_hierarchy,
                        "content": "",
                    }
                )
            elif sections:
                # 追加到当前章节内容
                sections[-1]["content"] += line + "\n"
            else:
                # 文档开头的无章节内容，归入前置章节
                sections.append(
                    {
                        "level": "0",
                        "title": doc_title,
                        "title_hierarchy": [doc_title],
                        "content": "",
                    }
                )
                sections[-1]["content"] += line + "\n"

        return sections

    async def chunk_by_pages(
        self, pages: list[dict], doc_meta: dict
    ) -> list[dict]:
        """按页分块（适用于 OCR 结果，每页有 text 字段）。

        将多页文本以空行拼接后，调用 chunk_document 统一进行结构感知分块。

        Args:
            pages: 页面列表，每页需包含 text 字段，例如
                [{"page_num": 1, "text": "...", "blocks": [...]}]。
            doc_meta: 文档元数据。

        Returns:
            list[dict]: 分块列表，格式同 chunk_document。
        """
        if not pages:
            logger.warning("按页分块输入页面列表为空", doc_id=doc_meta.get("doc_id"))
            return []

        # 拼接所有页面的文本，页面间以空行分隔以保留页面边界
        full_text = "\n\n".join(p["text"] for p in pages if p.get("text"))
        return await self.chunk_document(full_text, doc_meta)


# 模块级单例，默认 chunk_size=512、chunk_overlap=64
chunker = StructureAwareChunker()
