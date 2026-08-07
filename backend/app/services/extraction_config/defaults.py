"""抽取配置中心 - 默认全局配置。

当 KB 未自定义全局配置（kb_extraction_config 为空）时，使用本模块定义的
默认配置。区块命名规范为 ``retrieval`` / ``llm`` / ``kb_tool``，
不使用 phase 前缀。

类别级 top_k / confidence_threshold 通过 Schema 模板类别节点设置
（见 schema_configs），因此全局配置中不设置 doc_info_top_k /
heat_treatment_top_k 等专用字段，仅保留通用检索参数。
"""

from __future__ import annotations

# 抽取引擎名（全局统一，前端下拉与后端判断共用）
ENGINE_BASE_EXTRACT = "BaseExtract"
ENGINE_LANG_EXTRACT = "LangExtract"

# 默认全局配置（与 app.core.config.settings 的 EXTRACTION_V3_* 对齐）
DEFAULT_EXTRACTION_CONFIG: dict = {
    # 检索通用（Phase 2 类别召回 + Phase 3 上下文共用）
    "retrieval": {
        "top_k": 20,          # 类别召回 / 阶段融合 top_k
        "per_dim_top_k": 30,  # 每维独立检索 top_k
        "weights": {
            "path": 0.15,
            "title": 0.20,
            "content": 0.45,
            "type": 0.05,
            "structural": 0.15,
        },
        "default_confidence_threshold": 0.35,  # 默认置信度阈值（类别级可覆盖）
        "context_top_k": 20,      # 抽取上下文 top_k（拼接前按块数截断上限）
        "context_max_tokens": 28000,  # 上下文最大 token
        "context": {
            # 上下文 token 估算系数（字符/token）
            "chars_per_token": 1.5,
            # 上下文截断最后一个块时的最小保留字符数（低于此值则丢弃该块）
            "min_keep_chars": 200,
            # 上下文截断时追加的标记文本
            "truncate_marker": "\n[...内容截断...]",
        },
        # Phase 2 类别召回（判断文档存在哪些类别）
        "phase2": {
            "top_k": 5,               # 各维融合后用于判定类别命中的块数
            "per_dim_top_k": 10,      # 每维独立召回的块数
        },
        # 五维查询编码常量（query_embedder）
        "query_embed": {
            "content_max_chars": 2000,  # content 维 query 最大字符数
            "feature_repeat": 2,        # feature 名在 content 维重复次数
            "embed_max_length": 2048,   # 嵌入 max_length
            "type_query": "表格 数据结构 行列",  # type 维固定文本（示例，可按需修改）
            "dedupe_similarity_threshold": 0.85,  # 精简维条目语义去重相似度阈值
            "query_main_limit": 30,     # 主查询维条目上限（类别 Query 术语集未配置时回退此全局值）
            "query_refined_limit": 8,   # 精简维条目上限（类别 Query 术语集未配置时回退此全局值）
        },
        "reranker": {"enabled": True, "model": "", "top_n": 15},
    },
    # 抽取模型（按引擎分组，通过 llm.engine 切换当前引擎）
    "llm": {
        "engine": ENGINE_BASE_EXTRACT,   # BaseExtract | LangExtract
        "engines": {
            ENGINE_BASE_EXTRACT: {
                "temperature": 0.0,     # BaseExtract 线路采样温度
                "top_p": 0.1,
                "top_k": 20,
                "max_tokens": 32768,
                "timeout": 300,         # 单次 LLM 请求超时秒数
                "enable_thinking": False,  # vLLM close thinking mode
                "concurrency": {
                    "max_concurrency": 24,  # LLM 调用总并发上限（当前引擎）
                    "cross_category": 24,   # 类别间并发（BaseExtract 类别内串行=总并发）
                    "within_category": 1,   # 类别内并发（BaseExtract 串行）
                },
                "batch": {
                    "single_threshold": 8000,  # 长文本阈值
                    "batch_chars": 6000,       # 单批字符
                    "overlap": 500,            # 批间重叠
                    "context_truncate": 32000, # 单次输入截断保护
                },
            },
            ENGINE_LANG_EXTRACT: {
                "temperature": 0.0,     # LangExtract 线路采样温度（默认 0，同 BaseExtract）
                "top_p": 0.1,
                "top_k": 20,
                "max_tokens": 32768,
                "timeout": 300,
                "enable_thinking": False,
                "format_type": "JSON",
                "fence_output": False,
                "max_examples": 3,            # few-shot 示例数
                "passes": 2,                  # extraction_passes
                "context_window_chars": 28000,  # 跨块共指消解窗口
                "max_char_buffer": 40000,       # 单次 LLM 输入字符上限
                "concurrency": {
                    "max_concurrency": 24,  # LLM 调用总并发上限
                    "cross_category": 8,    # 类别间并发
                    "within_category": 3,   # 类别内并发（max_workers）
                },
            },
        },
    },
    # 脚本工具性能参数（kb_tool，供脚本引擎 embed/semantic_search/match_record 使用）
    "kb_tool": {
        "embed_batch_size": 32,   # embed 分批次大小
        "search_concurrency": 10, # 语义检索/匹配并发上限（共享信号量）
        "semantic_top_k": 5,      # semantic_search 默认 top_k
        "match_top_k": 1,         # match_record 内部检索 top_k
        "match_threshold": 0.90,  # match_record 默认相似度阈值
        # 脚本执行超时（秒），post/validation 脚本单条执行上限
        "script_timeout": 10,
    },
}


def get_default_config() -> dict:
    """返回默认全局配置的深拷贝（避免外部修改污染默认值）。"""
    import copy

    return copy.deepcopy(DEFAULT_EXTRACTION_CONFIG)