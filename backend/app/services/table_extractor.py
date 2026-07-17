"""表格结构化提取服务模块。

使用 pdfplumber 从 PDF 文件中提取表格结构，保留完整的行列关系，
转换为 Markdown 格式以便作为独立分块参与向量检索。

表格感知分块（P1.1 优化）解决的核心问题：
- 原分块策略（固定512字符+段落分割）会截断表格，破坏行列关系
- 化学成分表格、力学性能表格等数值类数据被分散到多个分块
- 导致 G1/G2 类查询（"铬含量是多少"）无法回答具体数值

提取流程：
    PDF 文件 → pdfplumber 逐页提取表格 → 结构化 dict → Markdown 文本

使用示例：
    from app.services.table_extractor import table_extractor

    tables = await table_extractor.extract_tables("/path/to/doc.pdf")
    # tables -> [{"table_id": 0, "page": 1, "headers": [...], "rows": [...], "markdown": "..."}]

    for table in tables:
        chunk = table_extractor.table_to_chunk(table, doc_meta)
"""

import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class TableExtractor:
    """表格结构化提取器。

    使用 pdfplumber 从 PDF 提取表格，保留完整行列结构，
    转换为 Markdown 格式用于独立分块。

    Attributes:
        _min_rows: 表格最小行数（含表头），少于该值的视为无效表格。
        _min_cols: 表格最小列数，少于该值的视为无效表格。
    """

    def __init__(self, min_rows: int = 2, min_cols: int = 2) -> None:
        """初始化表格提取器。

        Args:
            min_rows: 表格最小行数（含表头），默认 2。
            min_cols: 表格最小列数，默认 2。
        """
        self._min_rows = min_rows
        self._min_cols = min_cols

    async def extract_tables(self, pdf_path: str) -> list[dict[str, Any]]:
        """从 PDF 文件提取所有表格。

        使用 pdfplumber 逐页扫描表格，过滤无效表格（行/列数不足），
        为每个表格生成结构化 dict 与 Markdown 文本。

        Args:
            pdf_path: PDF 文件绝对路径。

        Returns:
            list[dict]: 表格列表，每个表格含：
                - table_id: 表格序号（从 0 开始）
                - page: 所在页码（从 1 开始）
                - headers: 列标题列表
                - rows: 行数据列表（每行为字符串列表）
                - markdown: Markdown 格式表格文本
                - row_count: 数据行数
                - col_count: 列数
            无表格或提取失败时返回空列表。
        """
        try:
            tables = await asyncio.to_thread(self._extract_tables_sync, pdf_path)
            logger.info(
                "PDF 表格提取完成",
                pdf_path=pdf_path,
                table_count=len(tables),
            )
            return tables
        except Exception as err:
            logger.warning("PDF 表格提取失败", pdf_path=pdf_path, error=str(err))
            return []

    def _extract_tables_sync(self, pdf_path: str) -> list[dict[str, Any]]:
        """同步提取 PDF 表格（在线程池中执行）。

        Args:
            pdf_path: PDF 文件路径。

        Returns:
            list[dict]: 表格列表。
        """
        import pdfplumber

        tables: list[dict[str, Any]] = []
        table_id = 0

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables()
                if not page_tables:
                    continue

                for raw_table in page_tables:
                    if not raw_table or len(raw_table) < self._min_rows:
                        continue

                    # 清洗单元格：None → 空字符串，去除首尾空白
                    cleaned = [
                        [str(cell).strip() if cell else "" for cell in row]
                        for row in raw_table
                    ]

                    # 检查列数
                    col_count = max(len(row) for row in cleaned)
                    if col_count < self._min_cols:
                        continue

                    # 补齐不等长行（pdfplumber 偶尔返回缺列的行）
                    for row in cleaned:
                        while len(row) < col_count:
                            row.append("")

                    # 第一行作为表头
                    headers = cleaned[0]
                    rows = cleaned[1:]

                    # 过滤全空行
                    rows = [r for r in rows if any(c for c in r)]

                    if not rows:
                        continue

                    table_dict: dict[str, Any] = {
                        "table_id": table_id,
                        "page": page_num,
                        "headers": headers,
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": col_count,
                    }
                    table_dict["markdown"] = self.table_to_markdown(table_dict)
                    tables.append(table_dict)
                    table_id += 1

        return tables

    @staticmethod
    def table_to_markdown(table: dict[str, Any]) -> str:
        """将表格结构转换为 Markdown 格式。

        保留完整行列关系，适合 LLM 理解表格内容。

        Args:
            table: 表格 dict，含 headers 和 rows。

        Returns:
            str: Markdown 格式表格字符串。
        """
        headers = table.get("headers", [])
        rows = table.get("rows", [])

        if not headers:
            return ""

        # 表头行
        header_line = "| " + " | ".join(headers) + " |"
        # 分隔行
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"
        # 数据行
        data_lines = [
            "| " + " | ".join(row) + " |"
            for row in rows
        ]

        return "\n".join([header_line, separator] + data_lines)

    def table_to_chunk(
        self,
        table: dict[str, Any],
        doc_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """将表格转换为带语义增强的独立分块。

        语义增强策略：在 Markdown 表格前添加描述性前缀（表格标识、列标题、
        数据行数），提升向量检索的匹配率。

        Args:
            table: 表格 dict，含 headers/rows/markdown 等字段。
            doc_meta: 文档元数据，含 doc_id/doc_title/file_name。

        Returns:
            dict: 分块 dict，含 chunk_id/text/metadata，metadata 中
                chunk_type="table" 标识表格分块。
        """
        doc_id = doc_meta.get("doc_id", "unknown")
        table_id = table.get("table_id", 0)
        headers = table.get("headers", [])
        markdown = table.get("markdown", "")
        page = table.get("page", 0)

        # 语义增强前缀：帮助嵌入模型理解表格上下文
        header_str = ", ".join(headers) if headers else "未命名列"
        enhanced_text = (
            f"【表格】文档 {doc_meta.get('doc_title', '')} 第{page}页 表格{table_id}\n"
            f"列标题：{header_str}\n"
            f"数据行数：{table.get('row_count', 0)}\n\n"
            f"{markdown}"
        )

        return {
            "chunk_id": f"{doc_id}_table_{table_id}",
            "text": enhanced_text,
            "metadata": {
                "doc_id": doc_id,
                "doc_title": doc_meta.get("doc_title", ""),
                "file_name": doc_meta.get("file_name", ""),
                "chunk_type": "table",
                "table_id": table_id,
                "table_page": page,
                "table_headers": headers,
                "table_row_count": table.get("row_count", 0),
                "title_chain": f"{doc_meta.get('doc_title', '')} > 表格{table_id}",
                "section_level": "table",
                "section_title": f"表格{table_id}",
                "chunk_index": table_id,
            },
        }


# 模块级单例
table_extractor = TableExtractor()
