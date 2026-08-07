"""v3 结构化抽取模块。

以 services/vector/ 五维向量为底座，配置中心 Schema 模板驱动类别构建，双线路 LLM 抽取。
"""

from app.services.extraction.llm_extract.llm_client import (
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
from app.services.extraction.retrieval.query_embedder import (
    QueryEmbedder,
    query_embedder,
)
from app.services.extraction.llm_extract.result_writer import (
    ResultWriter,
    result_writer,
)

__all__ = [
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
