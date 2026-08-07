"""v3 结构化抽取配置（EXTRACTION_V3_* 配置项的封装）。

从 ``app.core.config.settings`` 读取所有 ``EXTRACTION_V3_*`` 配置项，
提供类型安全的访问接口和派生属性（如 hybrid_search 权重字典）。

配置分组：
- LLM 端点：api_base / model / api_key / 并发 / 输出 tokens / 采样参数
- 抽取引擎：engine / fallback
- Phase 2 类别构建：置信度阈值 / 类别并发
- Phase 3 向量检索：top_k / 重排序 / 上下文 token 上限 / 五维权重
- Phase 4 LLM 抽取：LangExtract 参数 / glmocr 分批参数
- 后处理：归一化 / 跨类校验 / 去重阈值
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import settings


class ExtractionSettings:
    """v3 抽取配置访问器（只读，从全局 settings 派生）。

    所有属性直接映射 ``settings.EXTRACTION_V3_*``，不引入独立 env 文件，
    保证与全局配置一致。派生属性（如 ``hybrid_search_weights``）在首次
   访问时计算并缓存。
    """

    # ------------------------------------------------------------------
    # LLM 端点
    # ------------------------------------------------------------------

    @property
    def llm_api_base(self) -> str:
        return settings.EXTRACTION_V3_LLM_API_BASE

    @property
    def llm_model(self) -> str:
        return settings.EXTRACTION_V3_LLM_MODEL

    @property
    def llm_api_key(self) -> str:
        return settings.EXTRACTION_V3_LLM_API_KEY

    @property
    def llm_max_concurrency(self) -> int:
        """LLM 调用总并发上限（全局 Semaphore）。"""
        return settings.EXTRACTION_V3_LLM_MAX_CONCURRENCY

    @property
    def llm_max_output_tokens(self) -> int:
        return settings.EXTRACTION_V3_LLM_MAX_OUTPUT_TOKENS

    @property
    def llm_temperature(self) -> float:
        return settings.EXTRACTION_V3_LLM_TEMPERATURE

    @property
    def llm_top_p(self) -> float:
        return settings.EXTRACTION_V3_LLM_TOP_P

    @property
    def llm_top_k(self) -> int:
        return settings.EXTRACTION_V3_LLM_TOP_K

    # ------------------------------------------------------------------
    # 抽取引擎
    # ------------------------------------------------------------------

    @property
    def extraction_engine(self) -> str:
        """当前抽取引擎（配置驱动，BaseExtract / LangExtract）。"""
        return settings.EXTRACTION_V3_EXTRACTION_ENGINE

    @property
    def fallback_to_glmocr(self) -> bool:
        """LangExtract 失败时是否降级到 BaseExtract。"""
        return settings.EXTRACTION_V3_EXTRACTION_FALLBACK_TO_GLMOCR

    # ------------------------------------------------------------------
    # Phase 2 类别构建
    # ------------------------------------------------------------------

    @property
    def category_confidence_threshold(self) -> float:
        """feature 置信度阈值，低于此值或无召回则剔除。"""
        return settings.EXTRACTION_V3_CATEGORY_CONFIDENCE_THRESHOLD

    @property
    def category_concurrency(self) -> int:
        """feature 间调度并发上限。"""
        return settings.EXTRACTION_V3_CATEGORY_CONCURRENCY

    # ------------------------------------------------------------------
    # Phase 3 向量检索
    # ------------------------------------------------------------------

    @property
    def retrieval_top_k(self) -> int:
        return settings.EXTRACTION_V3_RETRIEVAL_TOP_K

    @property
    def retrieval_per_dim_top_k(self) -> int:
        return settings.EXTRACTION_V3_RETRIEVAL_PER_DIM_TOP_K

    @property
    def rerank_enabled(self) -> bool:
        return settings.EXTRACTION_V3_RETRIEVAL_RERANK_ENABLED

    @property
    def rerank_top_k(self) -> int:
        return settings.EXTRACTION_V3_RETRIEVAL_RERANK_TOP_K

    @property
    def context_max_tokens(self) -> int:
        return settings.EXTRACTION_V3_CONTEXT_MAX_TOKENS

    @property
    def hybrid_search_weights(self) -> dict[str, float]:
        """五维 hybrid_search 权重字典。

        从 ``EXTRACTION_V3_HYBRID_SEARCH_WEIGHTS``（逗号分隔 key:value）解析。
        """
        return _parse_weights(settings.EXTRACTION_V3_HYBRID_SEARCH_WEIGHTS)

    # ------------------------------------------------------------------
    # Phase 4 LLM 抽取 - LangExtract 线路
    # ------------------------------------------------------------------

    @property
    def langextract_passes(self) -> int:
        return settings.EXTRACTION_V3_LANGEXTRACT_PASSES

    @property
    def langextract_max_workers(self) -> int:
        """LangExtract 类别内分块并发数。"""
        return settings.EXTRACTION_V3_LANGEXTRACT_MAX_WORKERS

    @property
    def langextract_context_window_chars(self) -> int:
        return settings.EXTRACTION_V3_LANGEXTRACT_CONTEXT_WINDOW_CHARS

    @property
    def langextract_max_char_buffer(self) -> int:
        return settings.EXTRACTION_V3_LANGEXTRACT_MAX_CHAR_BUFFER

    # ------------------------------------------------------------------
    # Phase 4 LLM 抽取 - glmocr 线路
    # ------------------------------------------------------------------

    @property
    def large_table_threshold(self) -> int:
        """长文本阈值（≥此值触发表格边界感知分批）。"""
        return settings.EXTRACTION_V3_LARGE_TABLE_THRESHOLD

    @property
    def large_table_batch_chars(self) -> int:
        """单批字符上限。"""
        return settings.EXTRACTION_V3_LARGE_TABLE_BATCH_CHARS

    @property
    def glmocr_context_truncate(self) -> int:
        """单次 LLM 输入字符截断保护。"""
        return settings.EXTRACTION_V3_GLMOCR_CONTEXT_TRUNCATE

    @property
    def batch_overlap_chars(self) -> int:
        """批间重叠字符数。"""
        return settings.EXTRACTION_V3_BATCH_OVERLAP_CHARS

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------

    @property
    def item_normalize_sim_threshold(self) -> float:
        return settings.EXTRACTION_V3_ITEM_NORMALIZE_SIM_THRESHOLD

    @property
    def cross_validate_threshold(self) -> float:
        return settings.EXTRACTION_V3_CROSS_VALIDATE_THRESHOLD

    @property
    def dedup_sim_threshold(self) -> float:
        return settings.EXTRACTION_V3_DEDUP_SIM_THRESHOLD

    @property
    def edit_distance_threshold(self) -> float:
        return settings.EXTRACTION_V3_EDIT_DISTANCE_THRESHOLD

    # ------------------------------------------------------------------
    # 派生：根据引擎动态计算类别并发
    # ------------------------------------------------------------------

    @property
    def effective_category_concurrency(self) -> int:
        """根据引擎动态计算 feature 间并发。

        - LangExtract：category_concurrency（8），8×3=24 匹配 LLM 并发
        - BaseExtract：llm_max_concurrency（24），24×1=24 匹配 LLM 并发
        """
        if self.extraction_engine == "LangExtract":
            return self.category_concurrency
        # BaseExtract 线路类别内串行，可提高类别间并发
        return self.llm_max_concurrency


def _parse_weights(raw: str) -> dict[str, float]:
    """解析逗号分隔的 key:value 权重字符串。

    Args:
        raw: 如 "path:0.15,title:0.20,content:0.45,type:0.05,structural:0.15"

    Returns:
        dict: {"path": 0.15, "title": 0.20, ...}
    """
    weights: dict[str, float] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, val = part.split(":", 1)
        try:
            weights[key.strip()] = float(val.strip())
        except ValueError:
            continue
    return weights


@lru_cache(maxsize=1)
def get_extraction_settings() -> ExtractionSettings:
    """返回全局 ExtractionSettings 单例。"""
    return ExtractionSettings()
