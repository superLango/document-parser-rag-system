"""v3 结构化抽取模块（干净独立，不复用 v1/v2 代码）。

以 services/vector/ 五维向量为底座，配置中心 Schema 模板驱动类别构建，双线路 LLM 抽取。

模块组成：
- config: ExtractionSettings（EXTRACTION_V3_* 配置封装）
- models: 数据模型（ExtractionTarget / RetrievalContext / ExtractedRecord 等）
- llm_client: AsyncOpenAI 封装（vLLM 端点，glmocr 线路用）
- query_embedder: 五维 query 向量编码（Phase 2/3 共用）
- result_writer: 结果保存到任务目录
- prompts/: YAML 模板 + 字段描述定义
- schema_builder: 三类 schema 构建（基础信息/类别列表/热处理制度）
- pipeline: ExtractionPipeline 主编排（Phase 2-4）
- phase2_category/: 类别构建（category_builder + feature_filter）
- phase3_retrieval/: 向量检索（hybrid_searcher + reranker + context_assembler）
- phase4_extract/: LLM 抽取（双线路 + few_shot + batch + post_processor）

使用示例::

    from app.services.extraction.extraction_pipeline import ExtractionPipeline

    pipeline = ExtractionPipeline()
    result = await pipeline.run(task_id, doc_id)
"""

from app.services.extraction.extraction_config import (
    ExtractionSettings,
    get_extraction_settings,
)
from app.services.extraction.llm_client import (
    ExtractionLLMClient,
    llm_client,
)
from app.services.extraction.extraction_models import (
    CategoryResult,
    ExtractionResult,
    ExtractionTarget,
    RetrievedChunk,
    RetrievalContext,
    SkippedFeature,
)
from app.services.extraction.extraction_pipeline import (
    ExtractionPipeline,
    extraction_pipeline,
)
from app.services.extraction.query_embedder import (
    QueryEmbedder,
    query_embedder,
)
from app.services.extraction.result_writer import (
    ResultWriter,
    result_writer,
)

__all__ = [
    # config
    "ExtractionSettings",
    "get_extraction_settings",
    # llm_client
    "ExtractionLLMClient",
    "llm_client",
    # models
    "ExtractionTarget",
    "RetrievedChunk",
    "RetrievalContext",
    "CategoryResult",
    "ExtractionResult",
    "SkippedFeature",
    # query_embedder
    "QueryEmbedder",
    "query_embedder",
    # result_writer
    "ResultWriter",
    "result_writer",
    # pipeline
    "ExtractionPipeline",
    "extraction_pipeline",
]
