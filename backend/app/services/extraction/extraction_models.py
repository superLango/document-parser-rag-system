"""v3 抽取流程数据模型。

定义 Phase 2/3/4 各阶段流转的数据结构，使用 dataclass 保持轻量。
所有模型均为纯数据容器，不含业务逻辑。

核心数据流：
    ExtractionTarget（Phase 2 输出）
        → RetrievalContext（Phase 3 输出）
        → list[ExtractedRecord]（Phase 4 输出）
        → CategoryResult（后处理后）
        → ExtractionResult（最终结果）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ------------------------------------------------------------------
# Phase 2 输出：ExtractionTarget
# ------------------------------------------------------------------


@dataclass
class ExtractionTarget:
    """单个抽取类别目标（Phase 2 输出，Phase 3/4 输入）。

    配置驱动架构下，一个 ExtractionTarget 对应 Schema 模板中的一个类别
    （term_base 名称来源可展开为多个实例）。类别标题、查询、字段及其可选值
    均来自抽取配置中心。

    Attributes:
        feature: 类别名（展示名）。
        category_id: SchemaConfig 类别节点 ID。
        name_source: 名称来源（manual / term_base）。
        name_term_base_id: term_base 名称来源的术语集 ID。
        query_mode: 查询模式（当前固定 fixed）。
        fixed_query: 类别级固定查询文本。
        query_sources: Query 术语集配置（[{label, term_base_id, group_field, value_field, in_query, dedupe}]）。
        confidence_threshold: 类别级置信度阈值（可覆盖全局）。
        top_k: 类别级检索 top_k（可覆盖全局）。
        return_type: 返回类型（array / object）。
        fields: 类别字段定义（[{name, type, description, example, required, values: [可选值]}]）。
        query_terms: 检索查询词组（由 fixed_query + Query 术语集值组装）。
        confidence: Phase 2 检索置信度。
        schema: 该类别的 schema 定义（由 schema_builder 构建后填入）。
    """

    feature: str
    category_id: str | None = None
    template_id: str | None = None
    name_source: str = "manual"
    name_term_base_id: str | None = None
    query_mode: str = "fixed"
    fixed_query: str | None = None
    query_sources: list[dict] = field(default_factory=list)
    confidence_threshold: float | None = None
    top_k: int | None = None
    rerank_top_k: int | None = None
    max_tokens: int | None = None
    return_type: str = "array"
    fields: list[dict] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    schema: dict[str, Any] | None = None

    @property
    def item_names(self) -> list[str]:
        """所有字段可选值的扁平合并（兼容下游白名单 / 枚举注入）。"""
        names: list[str] = []
        for f in self.fields:
            for v in f.get("values", []) or []:
                if v and v not in names:
                    names.append(v)
        return names


# ------------------------------------------------------------------
# Phase 3 输出：RetrievalContext
# ------------------------------------------------------------------


@dataclass
class RetrievedChunk:
    """单条检索结果（hybrid_search 返回）。

    Attributes:
        chunk_id: 块 ID。
        score: 检索得分（融合后）。
        content: 子块正文（含表格增强文本）。
        parent_text: 父块完整原文（召回后替换子块用）。
        hierarchy_path: 层级路径。
        title: 标题。
        has_table: 是否含表格。
        source_pages: 来源页码。
        chunk_index: 在父块中的位置序号。
        level: 层级深度。
    """

    chunk_id: str = ""
    score: float = 0.0
    content: str = ""
    parent_text: str = ""
    hierarchy_path: str = ""
    title: str = ""
    has_table: bool = False
    source_pages: list[int] = field(default_factory=list)
    chunk_index: int = 0
    level: int = 0


@dataclass
class RetrievalContext:
    """单个 feature 的检索上下文（Phase 3 输出，Phase 4 输入）。

    包含拼接后的上下文文本、白名单 prompt、原始检索块（供调试）。

    Attributes:
        feature: 项目大类名。
        text: 拼接后的上下文文本（parent_text 替换 + 去重 + token 控制）。
        chunks: 原始检索块列表（供调试和后处理）。
        whitelist_prompt: 动态白名单 prompt（注入 LLM prompt）。
        rerank_scores: 重排序得分（若启用重排序）。
    """

    feature: str
    text: str = ""
    chunks: list[RetrievedChunk] = field(default_factory=list)
    whitelist_prompt: str = ""
    rerank_scores: list[float] = field(default_factory=list)


# ------------------------------------------------------------------
# Phase 4 输出：ExtractedRecord
# ------------------------------------------------------------------


@dataclass
class ExtractedRecord:
    """单条抽取记录（Phase 4 LLM 输出，后处理前）。

    Attributes:
        feature: 所属大类。
        data: 抽取的字段字典（如 {"材料牌号": "...", "项目名称": "...", ...}）。
        raw: LLM 原始输出（调试用）。
        _unverified: 是否未通过校验（跨类校验/归一化失败）。
        _reject_reason: 剔除原因（跨类混入/低置信度/重复）。
    """

    feature: str
    data: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    _unverified: bool = False
    _reject_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转为输出字典（剔除所有 `_` 开头的内部字段）。

        归一化 / 跨类校验阶段写入的 ``_normalize_score`` / ``_normalize_type`` /
        ``_method_year_filled`` 以及 ``_unverified`` / ``_reject_reason`` 等
        内部标记仅用于调试与测试面板，不进入最终抽取结果。
        """
        return {
            k: v for k, v in self.data.items() if not k.startswith("_")
        }


# ------------------------------------------------------------------
# 最终结果：CategoryResult / ExtractionResult
# ------------------------------------------------------------------


@dataclass
class CategoryResult:
    """单个类别的抽取结果（后处理后）。

    Attributes:
        feature: 项目大类名。
        records: 通过校验的记录列表。
        rejected: 被剔除的记录列表（含剔除原因）。
        timing: 该类别各阶段耗时（秒）。
    """

    feature: str
    records: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float] = field(default_factory=dict)


@dataclass
class SkippedFeature:
    """被剔除的 feature（无召回或置信度过低）。

    Attributes:
        feature: 项目大类名。
        reason: 剔除原因。
        confidence: 置信度。
    """

    feature: str
    reason: str
    confidence: float = 0.0


@dataclass
class ExtractionResult:
    """v3 抽取最终结果（result_writer 序列化为此结构）。

    Attributes:
        categories: 各类别抽取结果。
        summary: 汇总信息（总数、活跃 feature、剔除 feature）。
        timing: 总体各阶段耗时。
    """

    categories: list[CategoryResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典（用于 JSON 保存）。"""
        return {
            "categories": [
                {
                    "feature": c.feature,
                    "records": c.records,
                    "rejected": c.rejected,
                    "timing": c.timing,
                }
                for c in self.categories
            ],
            "summary": self.summary,
            "timing": self.timing,
        }
