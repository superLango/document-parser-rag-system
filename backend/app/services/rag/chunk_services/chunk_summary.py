"""语义块摘要服务。

为每个语义块生成标准化的"上下文摘要"，包含：
- core_topic: 核心主题
- related_sections: 关联章节索引
- key_entities: 关键实体列表（牌号、标准号、项目名）
- category: 所属类别

摘要作为 additional_context 注入抽取 prompt，提升 LLM 对语义块的理解。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger("chunk_summary")

# 关键实体正则模式
# 牌号：如 06Cr19Ni10、Q345B、SUS304、1Cr18Ni9Ti
# 注意：不使用 \b 词边界（中文上下文中 \b 行为不一致）
_GRADE_PATTERN = re.compile(
    r"([A-Z]{1,3}\d{1,3}[A-Z]?[A-Za-z0-9]{0,10}|"
    r"\d{1,2}[A-Z][A-Za-z0-9]{2,15}|"
    r"SUS\d{3}|"
    r"ZG\d{2,4}[A-Z]?)"
)
# 标准号：如 GB/T 1220、ASTM A240、JIS G4304
_STANDARD_PATTERN = re.compile(
    r"((GB/T|GB|ASTM|JIS|ISO|DIN|EN)\s*[\d\.]+[A-Za-z\-]*)"
)
# 检测项目关键词
_PROJECT_KEYWORDS = {
    "化学成分": ["碳", "C", "硅", "Si", "锰", "Mn", "磷", "P", "硫", "S", "铬", "Cr", "镍", "Ni"],
    "室温拉伸": ["抗拉强度", "屈服强度", "伸长率", "断面收缩率", "Rm", "Re", "A", "Z"],
    "高温拉伸": ["高温抗拉", "高温屈服", "高温伸长"],
    "冲击性能": ["冲击功", "冲击吸收", "夏比", "KV2", "Akv"],
    "硬度": ["布氏", "HBW", "洛氏", "HRC", "维氏", "HV"],
}


class ChunkSummaryService:
    """语义块摘要生成服务。

    使用规则提取关键实体（牌号、标准号、项目名），
    避免额外 LLM 调用开销。
    """

    def generate_summary(
        self,
        chunk_text: str,
        title_chain: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        """为语义块生成结构化摘要。

        Args:
            chunk_text: 语义块文本。
            title_chain: 所属章节路径。
            category: 所属类别。

        Returns:
            dict: 包含 core_topic/related_sections/key_entities/category 的摘要。
        """
        # 提取关键实体
        grades = self._extract_entities(chunk_text, _GRADE_PATTERN)
        standards = self._extract_entities(chunk_text, _STANDARD_PATTERN)
        detected_categories = self._detect_categories(chunk_text)

        # 核心主题：基于章节 + 类别 + 牌号
        primary_grade = grades[0] if grades else ""
        topic_parts = []
        if category:
            topic_parts.append(category)
        if primary_grade:
            topic_parts.append(f"牌号{primary_grade}")
        if title_chain:
            topic_parts.append(title_chain.split(">")[0].strip())
        core_topic = " - ".join(topic_parts) if topic_parts else "未知主题"

        # 关联章节
        related_sections = []
        if title_chain:
            related_sections = [s.strip() for s in title_chain.split(">") if s.strip()]

        return {
            "core_topic": core_topic,
            "related_sections": related_sections,
            "key_entities": {
                "grades": grades[:5],  # 最多5个牌号
                "standards": standards[:3],
                "detected_categories": detected_categories,
            },
            "category": category,
        }

    def render_summary_context(self, summary: dict[str, Any]) -> str:
        """将摘要渲染为 additional_context 可用的文本。

        Args:
            summary: 摘要字典。

        Returns:
            str: 可注入 prompt 的上下文文本。
        """
        parts = []
        if summary.get("core_topic"):
            parts.append(f"【语义块主题】{summary['core_topic']}")
        if summary.get("related_sections"):
            parts.append(f"【关联章节】{' > '.join(summary['related_sections'])}")
        entities = summary.get("key_entities", {})
        if entities.get("grades"):
            parts.append(f"【相关牌号】{', '.join(entities['grades'])}")
        if entities.get("standards"):
            parts.append(f"【相关标准】{', '.join(entities['standards'])}")
        return "\n".join(parts) if parts else ""

    @staticmethod
    def _extract_entities(text: str, pattern: re.Pattern) -> list[str]:
        """提取文本中匹配模式的实体，去重保序。"""
        seen: set[str] = set()
        result: list[str] = []
        for match in pattern.finditer(text):
            entity = match.group(1).strip()
            if entity and entity not in seen:
                seen.add(entity)
                result.append(entity)
        return result

    @staticmethod
    def _detect_categories(text: str) -> list[str]:
        """检测文本中涉及的类别关键词。"""
        detected: list[str] = []
        for category, keywords in _PROJECT_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    detected.append(category)
                    break
        return detected


# 模块级单例
chunk_summary_service = ChunkSummaryService()
