"""通用问答领域模板（general_qa）。

面向通用文档 RAG 问答场景，**不含结构化抽取**，仅做文档切分、向量化、
检索增强生成。适用于不固定结构、无需字段抽取的通用知识库。

特点：
- 无类别定义（categories 为空，抽取流程不触发）
- 无字段模板（field_templates 为空）
- 无正则规则（regex_rules 为空）
- 禁用基础字典同步（dict_config.enabled=False）
- 侧重 RAG 配置（向量检索参数、问答 LLM 参数）
"""

from __future__ import annotations

from app.domain_templates.base import (
    DictConfigDef,
    DomainTemplate,
)


GENERAL_QA_TEMPLATE = DomainTemplate(
    code="general_qa",
    name="通用问答知识库",
    description=(
        "面向通用文档 RAG 问答场景的模板，仅做文档切分、向量化与检索增强生成，"
        "不含结构化抽取。适用于不固定结构、无需字段抽取的通用知识库。"
    ),
    domain_code="general_qa",
    categories=[],  # 通用问答不进行结构化抽取
    field_templates=[],
    regex_rules=[],
    dict_config=DictConfigDef(
        enabled=False,  # 通用问答不启用基础字典
        match_threshold=0.5,
        whitelist_top_k=10,
        validation_top_k=1,
        validation_similarity_threshold=0.5,
        tables_mapping={},
    ),
    config_override={
        "ocr": {
            "enable_popo": True,
            "image_dpi": 200,
            "max_pages": 0,
        },
        "vector": {
            "top_k": 8,
            "rerank_pool": 20,
            "max_context_length": 8192,
        },
        "extraction": {
            "output_schema_mode": "never",  # 通用问答禁用 output_schema
            "passes": 1,
            "recall_classify_filter_enabled": False,
        },
        "qa": {
            "enable_cache": True,
        },
    },
    hook_template=None,
)
