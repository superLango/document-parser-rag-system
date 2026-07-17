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
from html.parser import HTMLParser

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.logging import get_logger

logger = get_logger(__name__)

# 匹配 "3.2.1 标题" 形式的编号章节标题
# 编号由数字与点号组成，标题为编号后的非空文本
_SECTION_PATTERN: re.Pattern[str] = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

# 中文语境下的递归分块分隔符，按优先级从高到低排列
# 优先在段落边界切分，其次换行、句号、分号、逗号、空格，最后逐字符
_DEFAULT_SEPARATORS: list[str] = ["\n\n", "\n", "。", "；", "，", " ", ""]

# 匹配 HTML <table>...</table> 块（非贪婪匹配，支持嵌套属性）
_HTML_TABLE_PATTERN: re.Pattern[str] = re.compile(
    r"<table[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL
)

# 表格 chunk 按行分组的最大行数（超过则分割，每组都带表头）
_TABLE_MAX_ROWS_PER_CHUNK: int = 15


class _HTMLTableParser(HTMLParser):
    """简易 HTML 表格解析器，提取行列数据。

    解析 <table> 中的 <tr> 行与 <td>/<th> 单元格，
    忽略 rowspan/colspan 合并语义（取文本内容）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] = []
        self._in_cell: bool = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag_lower = tag.lower()
        if tag_lower == "tr":
            self._current_row = []
        elif tag_lower in ("td", "th"):
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("td", "th") and self._current_row is not None:
            self._current_row.append("".join(self._current_cell).strip())
            self._in_cell = False
        elif tag_lower == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


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

    def _extract_html_tables(
        self, text: str
    ) -> tuple[list[dict], str]:
        """从 OCR 文本中提取 HTML <table> 块，返回结构化表格列表与清理后文本。

        OCR 服务（PaddleOCR 版面分析）会将识别到的表格以 HTML 格式嵌入
        解析文本。这些 HTML 表格包含完整的行列数据，但被当作普通文本
        分块时会被截断，破坏行列关系。本方法提取这些 HTML 表格为独立
        结构化表格，并从原文中移除以避免干扰常规分块。

        Args:
            text: OCR 解析文本，可能包含 HTML <table> 块。

        Returns:
            tuple[list[dict], str]:
                - 表格列表，每个表格含 headers/rows/markdown/page_hint/table_id
                - 移除 HTML 表格后的清理文本（保留表格前的标题行作为上下文）
        """
        tables: list[dict] = []
        matches = list(_HTML_TABLE_PATTERN.finditer(text))

        if not matches:
            return tables, text

        # 从后往前替换，避免偏移量变化
        cleaned_text = text
        for match in reversed(matches):
            html_block = match.group(0)
            start = match.start()

            # 尝试从表格前的文本中提取表格标题（如"表1 奥氏体型不锈钢的化学成分"）
            preceding_text = text[max(0, start - 200):start]
            title_match = re.search(
                r"((?:表|Table)\s*\d+[^<\n]{0,60})$", preceding_text, re.IGNORECASE
            )
            table_title = title_match.group(1).strip() if title_match else ""

            # 解析 HTML 表格为行列数据
            rows = self._html_table_to_rows(html_block)
            if not rows or len(rows) < 2:
                continue

            # 第一行作为表头
            headers = rows[0]
            data_rows = [r for r in rows[1:] if any(c for c in r)]
            if not data_rows:
                continue

            # 补齐不等长行
            col_count = max(len(headers), max(len(r) for r in data_rows))
            while len(headers) < col_count:
                headers.append("")
            for r in data_rows:
                while len(r) < col_count:
                    r.append("")

            table_dict = {
                "table_id": len(tables),
                "title": table_title,
                "headers": headers,
                "rows": data_rows,
                "row_count": len(data_rows),
                "col_count": col_count,
                "html": html_block,
            }
            table_dict["markdown"] = self._rows_to_markdown(headers, data_rows)
            tables.append(table_dict)

            # 从清理文本中移除 HTML 表格块
            cleaned_text = cleaned_text[:match.start()] + cleaned_text[match.end():]

        logger.info(
            "HTML 表格提取完成",
            table_count=len(tables),
            total_rows=sum(t["row_count"] for t in tables),
        )
        return tables, cleaned_text

    @staticmethod
    def _html_table_to_rows(html_block: str) -> list[list[str]]:
        """将 HTML 表格块解析为行列数据。

        使用内置 HTMLParser 解析 <tr>/<td> 标签，提取纯文本内容。
        忽略 rowspan/colspan 合并语义（简化处理，取文本内容）。

        Args:
            html_block: HTML <table>...</table> 字符串。

        Returns:
            list[list[str]]: 行列表，每行为单元格字符串列表。
        """
        parser = _HTMLTableParser()
        try:
            parser.feed(html_block)
        except Exception as err:
            logger.warning("HTML 表格解析失败", error=str(err))
            return []
        return parser.rows

    @staticmethod
    def _rows_to_markdown(
        headers: list[str], rows: list[list[str]], max_rows: int | None = None
    ) -> str:
        """将行列数据转换为 Markdown 格式表格。

        Args:
            headers: 表头列表。
            rows: 数据行列表。
            max_rows: 最多包含的数据行数，None 表示不限制。

        Returns:
            str: Markdown 格式表格字符串。
        """
        if not headers:
            return ""

        display_rows = rows[:max_rows] if max_rows else rows
        header_line = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = [
            "| " + " | ".join(row) + " |" for row in display_rows
        ]
        return "\n".join([header_line, separator] + data_lines)

    def _split_table_to_chunks(
        self,
        table: dict,
        doc_meta: dict,
        max_rows: int = _TABLE_MAX_ROWS_PER_CHUNK,
    ) -> list[dict]:
        """将大表格按行分组为多个 chunk，每组都带表头。

        确保每个 chunk 包含完整的表头 + 至多 max_rows 行数据，
        使向量检索能精确匹配到包含目标数据行的 chunk。

        Args:
            table: 表格 dict，含 headers/rows/title 等。
            doc_meta: 文档元数据。
            max_rows: 每组最大数据行数，默认 15。

        Returns:
            list[dict]: 分块列表。小表格返回单个 chunk，大表格返回多个。
        """
        doc_id = doc_meta.get("doc_id", "unknown")
        table_id = table.get("table_id", 0)
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        title = table.get("title", "")
        row_count = len(rows)

        # 小表格：单个 chunk
        if row_count <= max_rows:
            return [self._make_table_chunk(
                headers, rows, doc_meta, table_id, 0, 1, title, row_count
            )]

        # 大表格：按行分组
        chunks: list[dict] = []
        group_count = (row_count + max_rows - 1) // max_rows
        for group_idx in range(group_count):
            start = group_idx * max_rows
            end = min(start + max_rows, row_count)
            group_rows = rows[start:end]
            chunks.append(self._make_table_chunk(
                headers, group_rows, doc_meta, table_id,
                group_idx, group_count, title, row_count,
            ))

        logger.info(
            "大表格按行分组",
            table_id=table_id,
            total_rows=row_count,
            group_count=group_count,
            max_rows=max_rows,
        )
        return chunks

    def _make_table_chunk(
        self,
        headers: list[str],
        rows: list[list[str]],
        doc_meta: dict,
        table_id: int,
        group_idx: int,
        group_count: int,
        title: str,
        total_rows: int,
    ) -> dict:
        """生成单个表格分块。

        在 Markdown 表格前添加语义增强前缀（表格标题、列标题、行范围），
        提升向量检索的匹配率。

        Args:
            headers: 表头列表。
            rows: 本 chunk 包含的数据行。
            doc_meta: 文档元数据。
            table_id: 表格序号。
            group_idx: 分组序号（从 0 开始）。
            group_count: 总分组数（1 表示未分割）。
            title: 表格标题（如"表1 奥氏体型不锈钢的化学成分"）。
            total_rows: 原始表格总行数（用于元数据记录）。

        Returns:
            dict: 分块 dict，metadata.chunk_type="table"。
        """
        doc_id = doc_meta.get("doc_id", "unknown")
        markdown = self._rows_to_markdown(headers, rows)
        header_str = ", ".join(h for h in headers if h) or "未命名列"

        # 语义增强前缀
        title_part = f"（{title}）" if title else ""
        range_part = (
            f"第{group_idx + 1}-{group_idx + len(rows)}行/共{total_rows}行"
            if group_count > 1
            else f"共{len(rows)}行"
        )

        enhanced_text = (
            f"【表格{table_id}】{title_part}列标题：{header_str}\n"
            f"数据范围：{range_part}\n\n"
            f"{markdown}"
        )

        chunk_id = (
            f"{doc_id}_table_{table_id}"
            if group_count == 1
            else f"{doc_id}_table_{table_id}_g{group_idx}"
        )

        return {
            "chunk_id": chunk_id,
            "text": enhanced_text,
            "metadata": {
                "doc_id": doc_id,
                "doc_title": doc_meta.get("doc_title", ""),
                "file_name": doc_meta.get("file_name", ""),
                "chunk_type": "table",
                "table_id": table_id,
                "table_group": group_idx,
                "table_group_count": group_count,
                "table_title": title,
                "table_headers": headers,
                "table_row_count": len(rows),
                "table_total_rows": total_rows,
                "title_chain": f"{doc_meta.get('doc_title', '')} > 表格{table_id}{title_part}",
                "section_level": "table",
                "section_title": f"表格{table_id}{title_part}",
                "chunk_index": table_id * 100 + group_idx,
            },
        }

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

    async def chunk_document_with_tables(
        self,
        text: str,
        doc_meta: dict,
        pdf_path: str | None = None,
    ) -> list[dict]:
        """表格感知分块（P1.1 + P3 优化）。

        在常规结构感知分块基础上，从 OCR 文本和 PDF 中提取表格并作为独立分块。
        表格保留完整 Markdown 结构，附加语义增强前缀。大表格按行分组，
        确保每个 chunk 包含完整表头 + 数据行。

        优化流程（P3）：
        1. 优先从 OCR 文本中提取 HTML <table> 块（扫描版 PDF 的主要表格来源）
        2. 对移除表格后的文本进行常规结构感知分块
        3. 表格按行分组为多个 chunk（大表分割，每组带表头）
        4. 若提供 pdf_path，用 pdfplumber 补充提取矢量表格（作为补充）

        Args:
            text: 文档纯文本（OCR 结果，可能含 HTML 表格）。
            doc_meta: 文档元数据。
            pdf_path: 原始 PDF 文件路径，提供时启用 pdfplumber 表格提取。

        Returns:
            list[dict]: 分块列表（常规分块 + 表格分块）。
        """
        # 1. 从 OCR 文本提取 HTML 表格（P3 优化：扫描版 PDF 的主要表格来源）
        html_tables, cleaned_text = self._extract_html_tables(text)

        # 2. 对移除表格后的文本进行常规结构感知分块
        chunks = await self.chunk_document(cleaned_text, doc_meta)

        # 3. HTML 表格按行分组为独立 chunk
        table_chunk_count = 0
        for table in html_tables:
            table_chunks = self._split_table_to_chunks(table, doc_meta)
            chunks.extend(table_chunks)
            table_chunk_count += len(table_chunks)

        # 4. pdfplumber 补充提取（矢量 PDF 表格，作为补充）
        if pdf_path:
            try:
                from app.services.table_extractor import table_extractor

                pdf_tables = await table_extractor.extract_tables(pdf_path)
                if pdf_tables:
                    logger.info(
                        "表格感知分块：pdfplumber 补充提取到表格",
                        doc_id=doc_meta.get("doc_id"),
                        table_count=len(pdf_tables),
                    )
                    for table in pdf_tables:
                        table_chunk = table_extractor.table_to_chunk(table, doc_meta)
                        chunks.append(table_chunk)
                        table_chunk_count += 1
            except Exception as err:
                logger.warning(
                    "pdfplumber 表格提取失败，仅使用 HTML 表格分块",
                    doc_id=doc_meta.get("doc_id"),
                    error=str(err),
                )

        logger.info(
            "表格感知分块完成",
            doc_id=doc_meta.get("doc_id"),
            total_chunks=len(chunks),
            html_tables=len(html_tables),
            table_chunks=table_chunk_count,
        )
        return chunks


# 模块级单例，默认 chunk_size=512、chunk_overlap=64
chunker = StructureAwareChunker()
