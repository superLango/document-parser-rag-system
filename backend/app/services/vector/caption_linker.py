"""表格题注关联器（独立实现）。

调研 GLM-OCR ``semantic_indexer.py`` 的表格题注召回逻辑后，在当前项目中
独立实现。核心思路：

**问题**：表格的 HTML/Markdown 内容不利于语义检索，用户查询 "表3 的化学成分"
时直接对表格 HTML 做 embedding 召回效果差。

**方案**：通过表格题注（caption）编号匹配，将引用表格的题注文本关联到对应表格，
作为表格的检索文本。这样 content_vector 可通过题注语义召回对应表格。

关联机制（参照 GLM-OCR ``_find_table_captions``）：
1. **题注识别**：正则 ``表\\s*\\d+|见表|下表|如表`` 判断文本是否引用表格
2. **编号匹配**：从表格附近上下文提取表号（如 "表3"），再全文检索引用该表号的题注
3. **题注关联**：将题注文本设置到表格元素的 ``caption`` 字段，
   由 ``HierarchyChunker`` 前置到子块 content，使 ``content_vector`` 捕获题注语义

与 GLM-OCR 的差异：
- GLM-OCR 将题注用于 ``_generate_unit_path`` 生成语义单元路径标识
- 本实现将题注直接作为表格检索文本（更直接的召回路径）
- 不依赖坐标 proximity，仅用编号匹配（更精准，避免误关联）
"""

from __future__ import annotations

import logging
import re

from app.services.vector.vector_models import DocumentElement

logger = logging.getLogger(__name__)

# 表格题注识别正则（参照 GLM-OCR _is_table_caption）
_CAPTION_PATTERNS: list[str] = [
    r"表\s*\d+",  # 表3
    r"见表",
    r"下表",
    r"如下表",
    r"应符合表",
    r"如表",
]

# 提取表号的正则
_TABLE_NUM_PATTERN = re.compile(r"表\s*(\d+)")

# 题注引用表号的模式（参照 GLM-OCR _find_table_captions）
def _build_ref_patterns(target_num: str) -> list[str]:
    """构建引用指定表号的正则模式列表。"""
    return [
        rf"表\s*{target_num}(?!\d)",  # 表3（后不跟数字，避免表3匹配到表30）
        rf"见表\s*{target_num}(?!\d)",
        rf"如表\s*{target_num}(?!\d)",
        rf"下表\s*{target_num}(?!\d)",
    ]


class TableCaptionLinker:
    """表格题注关联器。

    遍历文档元素，为每个表格提取表号并关联题注文本，
    使表格可通过题注语义被召回。
    """

    # 提取表号的上下文窗口（表格前后查找的元素数）
    _NUM_LOOKUP_WINDOW = 3
    # 最多收集的引用题注数（避免过多噪声）
    _MAX_REFS = 2

    def link(self, elements: list[DocumentElement]) -> int:
        """关联表格题注，返回成功关联的表格数。

        为每个 ``table`` 类型元素填充 ``table_num`` 和 ``caption`` 字段。
        题注文本由两部分组成：
        1. 表格标题：表格附近包含 "表N" 的文本（表格自身的标题）
        2. 引用题注：全文中引用该表号的段落（提供额外语义上下文）

        Args:
            elements: 文档元素列表（原地修改 table 元素的 caption 字段）。

        Returns:
            成功关联题注的表格数量。
        """
        if not elements:
            return 0

        count = 0
        table_indices = [i for i, e in enumerate(elements) if e.type == "table"]

        for idx in table_indices:
            table_elem = elements[idx]

            # 1. 从表格附近上下文提取表号 + 表格标题
            table_num, title_text = self._extract_table_title(elements, idx)
            if not table_num:
                # 无法提取表号，跳过（保持表格独立，不强行关联）
                continue

            table_elem.table_num = table_num

            # 2. 全文检索引用该表号的题注
            refs = self._find_references(elements, table_num, exclude_idx=idx)

            # 3. 组合题注：标题 + 引用（去重）
            caption_parts: list[str] = []
            if title_text:
                caption_parts.append(title_text.strip())
            seen = {title_text.strip()} if title_text else set()
            for ref in refs[: self._MAX_REFS]:
                ref_clean = ref.strip()
                if ref_clean and ref_clean not in seen:
                    caption_parts.append(ref_clean)
                    seen.add(ref_clean)

            if caption_parts:
                table_elem.caption = " | ".join(caption_parts)
                count += 1
                logger.debug(
                    "表格题注关联",
                    extra={
                        "table_num": table_num,
                        "page": table_elem.page_num,
                        "caption": table_elem.caption[:80],
                    },
                )

        if count > 0:
            logger.info(
                "表格题注关联完成",
                extra={"total_tables": len(table_indices), "linked": count},
            )
        return count

    # ------------------------------------------------------------------
    # 表号提取与表格标题
    # ------------------------------------------------------------------

    def _extract_table_title(
        self, elements: list[DocumentElement], table_idx: int
    ) -> tuple[str, str]:
        """从表格附近上下文提取表号和表格标题文本。

        查找策略（按优先级）：
        1. 表格**前方**最近的可含表号的段落/标题（最常见：表标题在表格上方）
        2. 表格**后方**最近的段落/标题（少数情况：表标题在表格下方）

        Args:
            elements: 文档元素列表。
            table_idx: 表格元素索引。

        Returns:
            (表号, 标题文本) 元组，未找到时表号为空字符串。
            标题文本是包含 "表N" 的完整段落，作为表格的描述性标题。
        """
        # 1. 向前查找（表格标题通常在表格上方）
        for i in range(table_idx - 1, max(-1, table_idx - 1 - self._NUM_LOOKUP_WINDOW), -1):
            elem = elements[i]
            if elem.type not in ("paragraph", "title"):
                continue
            content = (elem.content or "").strip()
            if not content or len(content) > 100:
                # 跳过空内容或过长段落（表标题通常较短）
                continue
            match = _TABLE_NUM_PATTERN.search(content)
            if match:
                num = match.group(1)
                return f"表{num}", content

        # 2. 向后查找（表标题在表格下方的情况）
        for i in range(table_idx + 1, min(len(elements), table_idx + 1 + self._NUM_LOOKUP_WINDOW)):
            elem = elements[i]
            if elem.type not in ("paragraph", "title"):
                continue
            content = (elem.content or "").strip()
            if not content or len(content) > 100:
                continue
            match = _TABLE_NUM_PATTERN.search(content)
            if match:
                num = match.group(1)
                return f"表{num}", content

        return "", ""

    # ------------------------------------------------------------------
    # 全文引用检索
    # ------------------------------------------------------------------

    @staticmethod
    def _find_references(
        elements: list[DocumentElement],
        table_num: str,
        exclude_idx: int,
    ) -> list[str]:
        """全文检索引用指定表号的题注文本。

        参照 GLM-OCR ``_find_table_captions``：通过正则匹配 "表N"、"见表N"、
        "如表N" 等模式，找到全文中引用该表格的段落。

        Args:
            elements: 文档元素列表。
            table_num: 表号（如 "表3"）。
            exclude_idx: 排除的元素索引（表格标题元素，避免重复）。

        Returns:
            引用该表号的题注文本列表（按文档顺序）。
        """
        num_match = re.search(r"(\d+)", table_num)
        if not num_match:
            return []
        target_num = num_match.group(1)
        patterns = _build_ref_patterns(target_num)

        refs: list[str] = []
        for i, elem in enumerate(elements):
            if i == exclude_idx:
                continue
            if elem.type not in ("paragraph", "title"):
                continue
            content = (elem.content or "").strip()
            if not content:
                continue
            for pattern in patterns:
                if re.search(pattern, content):
                    refs.append(content)
                    break

        return refs


# 模块级单例
table_caption_linker = TableCaptionLinker()
