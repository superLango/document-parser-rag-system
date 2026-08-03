"""v3 抽取流程数据模型。

定义 Phase 2/3/4 各阶段流转的数据结构，使用 dataclass 保持轻量。
所有模型均为纯数据容器，不含业务逻辑。

核心数据流：
    ExtractionTarget（Phase 2 输出）
        → RetrievalContext（Phase 3 输出）
        → list[ExtractedRecord]（Phase 4 输出）
        → CategoryResult / HeatTreatmentResult（后处理后）
        → ExtractionResult（最终结果）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ------------------------------------------------------------------
# 基础表数据（从 base_data.loader 加载，Phase 2 使用）
# ------------------------------------------------------------------


@dataclass
class ItemInfo:
    """sm_item 检测项目信息（字典形式，便于序列化）。

    Attributes:
        name: 标准项目名（sm_item.NAME）。
        english_name: 英文名。
        aliases: 别名列表（ITEM_ALIAS 拆分）。
        unit: 标准单位。
        feature: 所属大类名。
    """

    name: str
    english_name: str = ""
    aliases: list[str] = field(default_factory=list)
    unit: str = ""
    feature: str = ""

    @classmethod
    def from_orm(cls, orm_obj: Any) -> ItemInfo:
        """从 SmItem ORM 对象构造。

        Args:
            orm_obj: SmItem ORM 实例。
        """
        aliases: list[str] = []
        if orm_obj.item_alias:
            aliases = [s.strip() for s in orm_obj.item_alias.split(",") if s.strip()]
        return cls(
            name=orm_obj.name,
            english_name=orm_obj.english_name or "",
            aliases=aliases,
            unit=orm_obj.unit or "",
            feature=orm_obj.feature,
        )

    def to_dict(self) -> dict[str, Any]:
        """转为字典（用于白名单 prompt 注入）。"""
        return {
            "name": self.name,
            "english_name": self.english_name,
            "aliases": self.aliases,
            "unit": self.unit,
            "feature": self.feature,
        }


@dataclass
class MethodInfo:
    """sm_method 检测方法信息。

    Attributes:
        name: 方法全名。
        method_code: 标准号（如 GB/T 223.7-2002）。
        feature: 方法分类（sm_method.FEATURE）。
    """

    name: str
    method_code: str = ""
    feature: str = ""

    @classmethod
    def from_orm(cls, orm_obj: Any) -> MethodInfo:
        """从 SmMethod ORM 对象构造。"""
        return cls(
            name=orm_obj.name or "",
            method_code=orm_obj.method_code or "",
            feature=orm_obj.feature or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method_code": self.method_code,
            "feature": self.feature,
        }


# ------------------------------------------------------------------
# Phase 2 输出：ExtractionTarget
# ------------------------------------------------------------------


@dataclass
class ExtractionTarget:
    """单个 feature 的抽取目标（Phase 2 输出，Phase 3/4 输入）。

    一个 ExtractionTarget 对应一个保留的 feature（项目大类），
    包含该 feature 下的全部 items 和 methods，以及 schema 定义。

    Attributes:
        feature: 项目大类名（sm_feature.NAME）。
        items: 该 feature 下的检测项目列表。
        methods: 该 feature 关联的检测方法列表。
        confidence: Phase 2 检索置信度（max score）。
        schema: 该 feature 的 schema 定义（由 schema_builder 构建后填入）。
    """

    feature: str
    items: list[ItemInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    confidence: float = 0.0
    schema: dict[str, Any] | None = None

    @property
    def item_names(self) -> list[str]:
        """标准项目名列表（用于 enum 约束）。"""
        return [it.name for it in self.items if it.name]

    @property
    def method_names(self) -> list[str]:
        """方法名列表（用于 enum 约束）。"""
        return [m.name for m in self.methods if m.name]

    @property
    def method_codes(self) -> list[str]:
        """方法标准号列表（用于年代号匹配）。"""
        return [m.method_code for m in self.methods if m.method_code]


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
        """转为输出字典（剔除内部字段）。"""
        result = dict(self.data)
        if self._unverified:
            result["_unverified"] = True
        if self._reject_reason:
            result["_reject_reason"] = self._reject_reason
        return result


# ------------------------------------------------------------------
# 最终结果：CategoryResult / HeatTreatmentResult / ExtractionResult
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
class HeatTreatmentResult:
    """热处理制度抽取结果。

    Attributes:
        records: 热处理记录列表。
        timing: 耗时。
    """

    records: list[dict[str, Any]] = field(default_factory=list)
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
        doc_info: 标准基本信息（标准名称、标准编号）。
        categories: 各类别抽取结果。
        heat_treatment: 热处理制度结果。
        summary: 汇总信息（总数、活跃 feature、剔除 feature）。
        timing: 总体各阶段耗时。
    """

    doc_info: dict[str, Any] = field(default_factory=dict)
    categories: list[CategoryResult] = field(default_factory=list)
    heat_treatment: HeatTreatmentResult = field(default_factory=HeatTreatmentResult)
    summary: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典（用于 JSON 保存）。"""
        return {
            "doc_info": self.doc_info,
            "categories": [
                {
                    "feature": c.feature,
                    "records": c.records,
                    "rejected": c.rejected,
                    "timing": c.timing,
                }
                for c in self.categories
            ],
            "heat_treatment": {
                "records": self.heat_treatment.records,
                "timing": self.heat_treatment.timing,
            },
            "summary": self.summary,
            "timing": self.timing,
        }
