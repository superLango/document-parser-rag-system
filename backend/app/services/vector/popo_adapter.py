"""Popo 输出适配器：doc_blocks → DocumentElement 列表。

将 Popo 后处理的 ``doc_blocks``（含 level/contd 字段）转换为统一的
``DocumentElement`` 列表，供后续父子块切分与五维向量化使用。

Popo 的 ``level`` 字段（-1=非标题，1-4=标题层级）映射为
``DocumentElement.hierarchy_level``，并据此构建 ``hierarchy_path``。
"""

from __future__ import annotations

import logging
import re

from app.services.vector.vector_models import DocumentElement

logger = logging.getLogger(__name__)

# Popo type → DocumentElement.type 映射
_POPO_TYPE_MAP: dict[str, str] = {
    "text": "paragraph",
    "title": "title",
    "table": "table",
    "image_caption": "paragraph",
    "table_caption": "paragraph",
    "image": "paragraph",
}


class PopoAdapter:
    """Popo doc_blocks → DocumentElement 适配器。"""

    @staticmethod
    def adapt(doc_blocks: list[dict]) -> list[DocumentElement]:
        """将 Popo 的 doc_blocks 转换为 DocumentElement 列表。

        处理逻辑：
        1. 映射 type（text→paragraph, title→title, table→table）
        2. 映射 level（Popo level → hierarchy_level）
        3. 构建 hierarchy_path（遍历 level 栈）
        4. 合并 contd 标记的跨页段落
        5. 清洗标题内容（移除 Markdown # 前缀）

        Args:
            doc_blocks: Popo 推理输出的 block 列表，每个 block 含
                type/content/page/bbox/level/contd 等字段。

        Returns:
            DocumentElement 列表（已合并跨页段落，已构建层级路径）。
        """
        if not doc_blocks:
            return []

        elements: list[DocumentElement] = []
        # 层级栈：[(level, title_text), ...]
        hierarchy_stack: list[tuple[int, str]] = []
        global_index = 0

        for block in doc_blocks:
            popo_type = block.get("type", "text")
            elem_type = _POPO_TYPE_MAP.get(popo_type, "paragraph")
            content = block.get("content", "") or ""
            level = block.get("level", -1)
            page = block.get("page", 1)
            bbox = block.get("bbox", [0, 0, 0, 0])
            # bbox 归一化坐标 → 像素近似（逆映射不需要精确，仅用于排版参考）
            if len(bbox) == 4 and all(0 <= v <= 2 for v in bbox):
                bbox = [v * 1000 for v in bbox]

            # 清洗标题内容（移除 Markdown # 前缀）
            clean_content = content
            if elem_type == "title":
                clean_content = re.sub(r"^#+\s*", "", content).strip()
                # 如果清洗后为空，跳过
                if not clean_content:
                    continue

            # 构建 hierarchy_path
            # 注意：Popo 的 level 字段不可靠（真正标题常为 -1，正文段落反被赋 level>0），
            # 因此只信任 type=title，从内容推断层级。
            hierarchy_level = 0
            if elem_type == "title":
                hierarchy_level = PopoAdapter._infer_title_level(content, clean_content)
                # 弹栈直到栈顶 level < 当前 level
                while hierarchy_stack and hierarchy_stack[-1][0] >= hierarchy_level:
                    hierarchy_stack.pop()
                hierarchy_stack.append((hierarchy_level, clean_content))

            # 构建路径
            hierarchy_path = " > ".join(title for _, title in hierarchy_stack) if hierarchy_stack else ""

            elements.append(
                DocumentElement(
                    type=elem_type,
                    bbox=[float(v) for v in bbox],
                    content=clean_content,
                    page_num=page,
                    native_label=popo_type,
                    font_height=float(bbox[3] - bbox[1]) if len(bbox) >= 4 else 0.0,
                    hierarchy_level=hierarchy_level,
                    hierarchy_path=hierarchy_path,
                    index=global_index,
                )
            )
            global_index += 1

        # 合并 contd 标记的跨页段落
        elements = PopoAdapter._merge_contd(elements, doc_blocks)

        logger.info(
            "Popo doc_blocks 适配完成",
            extra={
                "total_blocks": len(doc_blocks),
                "total_elements": len(elements),
                "titles": sum(1 for e in elements if e.type == "title"),
            },
        )
        return elements

    @staticmethod
    def _infer_title_level(raw_content: str, clean_content: str) -> int:
        """从标题内容推断层级（不依赖 Popo 的 level 字段）。

        优先级：
        1. Markdown ``#`` 前缀数量（``## `` → 2）
        2. 标题编号点号数（``7.3.4`` → 3，``7.4`` → 2，``7`` → 1）
        3. 特殊标题（``附录``/``前 言`` → 1）
        4. 兜底 → 2

        Args:
            raw_content: 原始内容（含 Markdown ``#`` 前缀）。
            clean_content: 清洗后的内容（已移除 ``#`` 前缀）。

        Returns:
            int: 层级深度（1~6）。
        """
        # 1. Markdown # 前缀
        md_match = re.match(r"^(#{1,6})\s", raw_content)
        if md_match:
            return len(md_match.group(1))

        # 2. 标题编号（X.Y.Z 格式，点号数+1=层级）
        num_match = re.match(r"^(\d+)(\.\d+)+", clean_content)
        if num_match:
            first_token = clean_content.split()[0] if clean_content.split() else ""
            return first_token.count(".") + 1

        # 单数字开头：如 "1 范围"、"7 技术要求"
        if re.match(r"^\d+\s", clean_content):
            return 1

        # 3. 特殊标题
        if clean_content.startswith("附") or "前" in clean_content[:4] and "言" in clean_content[:4]:
            return 1

        # 4. 兜底
        return 2

    @staticmethod
    def _merge_contd(
        elements: list[DocumentElement], doc_blocks: list[dict]
    ) -> list[DocumentElement]:
        """合并 contd 标记的跨页段落。

        Popo 的 contd 字段：如果 block A 的 contd = B.id，
        表示 A 是 B 的续段（跨页截断），应合并 B+A。

        Args:
            elements: 已转换的 DocumentElement 列表。
            doc_blocks: 原始 Popo doc_blocks。

        Returns:
            合并后的 DocumentElement 列表。
        """
        # 构建 id → contd 映射
        contd_map: dict[int, int] = {}  # block_id → contd_target_id
        for block in doc_blocks:
            contd = block.get("contd", -1)
            if contd > 0:
                contd_map[block["id"]] = contd

        if not contd_map:
            return elements

        # 找出需要合并的元素对
        # contd_map: {A.id: B.id} 表示 A 续接 B
        # 需要将 A 的内容追加到 B 后面
        merge_targets: dict[int, int] = {}  # A_index → B_index (在 elements 中的索引)
        id_to_index: dict[int, int] = {}
        for i, block in enumerate(doc_blocks):
            id_to_index[block["id"]] = i

        for a_id, b_id in contd_map.items():
            if a_id in id_to_index and b_id in id_to_index:
                merge_targets[id_to_index[a_id]] = id_to_index[b_id]

        if not merge_targets:
            return elements

        # 执行合并
        merged_indices: set[int] = set()
        result: list[DocumentElement] = []

        for i, elem in enumerate(elements):
            if i in merged_indices:
                continue
            if i in merge_targets:
                # 当前元素是续段，跳过（内容已合并到目标）
                continue

            # 检查是否有续段指向当前元素
            current = elem
            # 找所有 contd 指向当前元素的
            for j, target_j in merge_targets.items():
                if target_j == i and j not in merged_indices:
                    # 合并 elements[j] 到 current
                    next_elem = elements[j]
                    current = DocumentElement(
                        type=current.type,
                        bbox=[
                            min(current.bbox[0], next_elem.bbox[0]),
                            min(current.bbox[1], next_elem.bbox[1]),
                            max(current.bbox[2], next_elem.bbox[2]),
                            max(current.bbox[3], next_elem.bbox[3]),
                        ],
                        content=current.content + " " + next_elem.content,
                        page_num=current.page_num,
                        native_label=current.native_label,
                        font_height=current.font_height,
                        hierarchy_level=current.hierarchy_level,
                        hierarchy_path=current.hierarchy_path,
                        index=current.index,
                    )
                    merged_indices.add(j)

            result.append(current)

        logger.info("跨页段落合并: %d 处", len(merge_targets))
        return result
