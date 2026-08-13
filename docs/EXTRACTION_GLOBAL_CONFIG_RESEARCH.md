# 结构化抽取全局配置 · 调研与设计建议

- 日期：2026-08-13
- 状态：调研已完成，落地实施见 [EXTRACTION_GLOBAL_CONFIG_IMPLEMENTATION_PLAN.md](EXTRACTION_GLOBAL_CONFIG_IMPLEMENTATION_PLAN.md)（P1-P4 已交付）
- 范围：仅针对**结构化抽取**的全局配置（检索召回、LLM 抽取参数、脚本工具性能），不含系统/项目级配置（数据库、Redis、存储、解析管线、权限等）。
- 依据：
  - 原项目实际源码：`document-parser-rag-system/frontend/src/views/Kb/ExtractionConfig.vue`（全局配置页）、`backend/app/api/v1/endpoints/extraction_config.py`、`backend/app/services/extraction_config/{defaults,config_validator,resolver}.py`
  - 市面系统公开文档：RAGFlow、Dify、FastGPT、LightRAG（本地源码）、TextIn ParseX/DocFlow
  - 当前项目：`backend/app/core/config.py`、`backend/app/services/indexing/{retrieval,bm25}.py`、`backend/app/services/embedding/embedding_service.py`、`backend/app/services/extraction_config_service.py`

## 1. 调研结论摘要

1. 原项目的“全局配置”是**知识库级抽取运行时参数**，分三大区块：`retrieval`（检索召回/上下文）、`llm`（抽取引擎与模型调用参数）、`kb_tool`（脚本工具性能）；采用“默认值 + 显式覆盖”，且原项目提交前强制完整性校验（不回退默认值，最严格模式）。
2. 市面主流 RAG 系统（RAGFlow/Dify/FastGPT）通过前端可配置的维度高度一致：**分块参数、嵌入模型、检索模式与召回数、相似度阈值、多路召回权重（RRF）、重排模型与开关、引用上限、问题改写开关**；抽取类产品（TextIn 等）主要配置**解析选项（版面/表格/公式/OCR）、字段与表格模板、样本标注、输出格式**。
3. 当前项目尚未实现 LLM 抽取链路与全局配置存储；现有相关参数分散在 `app/core/config.py`（检索/嵌入/BM25）和 `extraction_config_service.py`（脚本超时）等位置。
4. 建议当前项目全局配置按“**检索召回 / LLM 抽取 / 脚本工具 / 上下文组装**”四块设计，模型与端点类资源仍放“资源与配置”（不重复配置），解析/OCR/嵌入底层权重等系统级参数不放全局配置。

## 2. 原项目全局配置模块详解

### 2.1 配置结构（`kb_extraction_config.content`）

来源：`defaults.py::DEFAULT_EXTRACTION_CONFIG` 与 `ExtractionConfig.vue` 全局页模板。

| 区块 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| retrieval | top_k | 20 | 类别召回/阶段融合 top_k |
| | per_dim_top_k | 30 | 每维独立检索 top_k |
| | weights.path / title / content / type / structural | 0.15/0.2/0.45/0.05/0.15 | 五维加权 |
| | default_confidence_threshold | 0.35 | 类别命中默认置信阈值（类别级可覆盖） |
| | context_top_k / context_max_tokens | 20 / 28000 | 抽取上下文块数/token 上限 |
| | context.chars_per_token / min_keep_chars / truncate_marker | 1.5 / 200 / "\n[...内容截断...]" | 上下文估算与截断 |
| | phase2.top_k / per_dim_top_k | 5 / 10 | 类别存在性判定召回 |
| | query_embed.content_max_chars / feature_repeat / embed_max_length / type_query / dedupe_similarity_threshold | 2000 / 2 / 2048 / "表格 数据结构 行列" / 0.85 | 五维 Query 编码参数 |
| | reranker.enabled / model / top_n | true / "" / 15 | 重排开关/模型/保留数 |
| | hybrid.enabled / dense_candidate_k / keyword_top_k / rrf_k / dense_weight / keyword_weight / keyword_min_hits | true / 80 / 60 / 60 / 1.0 / 1.2 / 1 | 稠密+BM25 混合与 RRF |
| llm | engine | BaseExtract | 抽取引擎切换（BaseExtract/LangExtract） |
| | engines.BaseExtract.temperature / top_p / top_k / max_tokens / timeout / enable_thinking | 0.0 / 0.1 / 20 / 32768 / 300 / false | 采样与超时 |
| | engines.BaseExtract.concurrency.max_concurrency / cross_category / within_category | 24 / 24 / 1 | LLM 并发 |
| | engines.BaseExtract.batch.single_threshold / batch_chars / overlap / context_truncate | 8000 / 6000 / 500 / 32000 | 长文本分批 |
| | engines.LangExtract.format_type / fence_output / max_examples / passes / context_window_chars / max_char_buffer | JSON / false / 3 / 2 / 28000 / 40000 | 结构化强约束引擎 |
| kb_tool | embed_batch_size / search_concurrency / semantic_top_k / match_top_k / match_threshold / script_timeout | 32 / 10 / 5 / 1 / 0.9 / 10 | 脚本工具性能与安全 |

### 2.2 后端机制

- 存储：`kb_extraction_config` 表按 KB 存一份 `content`（JSONB），`version` 自增；`GET/PUT /extraction-config/global` 读写（editor+ 可写）。
- 解析：`ExtractionConfigResolver` 组装为 `ExtractionDomainConfig`，提供 `engine_params()/total_llm_concurrency()/context_top_k()/kb_tool()` 等便捷访问；运行时不回退默认值，缺失即抛错。
- 校验：`config_validator.validate_extraction_config` 提交前全量校验——所有有效参数必须显式填写、LLM 端点三元组必须有效、至少一个启用 Schema 模板、必须配置 Prompt 模板、开启重排时模型必须可加载。
- 分层：LLM 端点（api_base/model）放在“资源与配置”的 KB 配置（`kb.config.extraction`），全局配置只放运行参数，二者分离。

## 3. 市面 RAG / 文档结构化抽取系统前端可配置项调研

### 3.1 RAGFlow（RAG）

公开文档与社区资料可见的知识库/检索前端可配置项：

- 知识库创建：嵌入模型选择、建议文本块大小（文本按换行/##/分号预切分后按块大小拼装）、解析方法（如 DeepDoc 版面解析、RAPTOR 等模板/方法选择）。
- 切片配置：切片方法（delimiter/tokenization/vision 等）、块大小与重叠、页面排名（Page rank 0-100 加权）、自动关键词（0-30）、自动问题（0-10）。
- 检索组件：Top N（默认 8）、相似度阈值、关键词/向量权重（未选重排时加权关键词相似度 + 向量余弦）、重排模型选择（可选）。
- 证据：RAGFlow 官方“运行检索测试/检索组件”文档、`cnblogs.com/rslai/p/19047825`（页面排名/自动关键词/自动问题）。

### 3.2 Dify（RAG 平台）

- 分块设置：分隔符、最大块长度、块重叠；分块模式（普通 / 父子分块：父块 Paragraph/Full Doc、子块独立分隔符与长度）；文本预处理清理规则（连续空白/换行合并、去除 URL/邮箱等）；块预览与手动微调。
- 索引模式：高质量（embedding + 语义检索）与经济模式（关键词索引）。
- 检索设置：Top K、Score 阈值、Rerank 启用与模型、多路召回（语义/全文/混合加权）、权重设置。
- 证据：Dify 官方文档 “Configure the Chunk Settings”。

### 3.3 FastGPT（RAG）

- 向量模型（按数据集配置）、分块大小与重叠（可调至 1500/3000 等社区经验值）。
- 搜索模式：语义检索 / 全文检索 / 混合检索；RRF 融合（对重排、向量、全文结果合并）。
- 重排模型与开关、重排权重；引用上限（按 token 而非 top_k）；最低相关度过滤；问题优化（指代消除/问题扩展）开关。
- 证据：FastGPT 官方文档 “知识库搜索方案和参数”。

### 3.4 LightRAG（图+向量 RAG，本地源码 `lightrag/lightrag/lightrag.py`）

- 分块：`chunk_token_size`、`chunk_overlap_token_size`、chunker 类型（fixed_token/recursive_character 等，经 `addon_params['chunker']`）。
- 模型：`llm_model_func`/`llm_model_kwargs`、`llm_model_max_async`、`embedding_func`/`embedding_func_kwargs`、`embedding_chunk_overlap_token_size`、`embedding_func_max_async`；`rerank_model_func`/`rerank_model_max_async`。
- 存储：`kv_storage`/`vector_storage`/`graph_storage`/`doc_status_storage` 及各自 kwargs；`max_parallel_insert` 等并发参数。
- 检索：`cosine_threshold`、top_k 等。
- 特点：以上多数是代码/配置级而非可视化前端，但可作为我们 LLM 兼容体系的底层参数来源。

### 3.5 TextIn ParseX / DocFlow（文档结构化抽取）

- 解析接口选项：`page_details`（返回版面元素明细）、`table_flavor=none`（关闭表格识别但保留段落/坐标/阅读顺序）、公式/表格/图片输出开关、语言与 OCR 参数、Markdown 输出。
- 抽取配置：文件类别管理，每个类别可配置字段、表格字段、样本文件，用于文档分类与智能抽取；可视化前端支持解析结果校对、坐标溯源、目录树跳转、Markdown 导出。
- 证据：TextIn 官网新闻与 DocFlow 快速启动文档。

### 3.6 共性总结

- RAG 类前端可配置：**分块（大小/重叠/模式）、嵌入模型、检索模式与 Top K、相似度阈值、RRF/多路权重、重排开关与模型、引用上限、问题优化开关**。
- 抽取类前端可配置：**解析选项（版面/表格/公式/OCR）、字段/表格模板、样本标注、输出格式、结果校对与导出**。
- 与当前项目契合点：我们已有 Schema/Prompt/规则/脚本四大配置，全局配置应补齐“检索召回 + LLM 参数 + 上下文组装 + 脚本工具性能”四类运行时旋钮。

## 4. 当前项目现状

| 配置来源 | 现状 | 是否建议移入抽取全局配置 |
|----------|------|--------------------------|
| `settings.RETRIEVAL_TOP_K / CANDIDATE_MULT` | 检索默认 top_k、候选放大 | ✅ 建议（检索召回） |
| `settings.RETRIEVAL_TITLE_WEIGHT / CONTENT_WEIGHT` | title+content 双路权重 | ✅ 建议（五维权重简化版） |
| `settings.RETRIEVAL_RRF_K / DENSE_WEIGHT / KEYWORD_WEIGHT` | RRF 常数与稠密/词法权重 | ✅ 建议 |
| `settings.BM25_K1 / BM25_B` | BM25 平滑参数 | ✅ 建议（词法路，可先保留系统默认） |
| `settings.EMBEDDING_BATCH_SIZE / MAX_LENGTH / DIM` | 嵌入运行时参数 | ⚠️ 建议留系统级（底层权重/性能），仅 `embed_max_length` 类查询编码参数进全局 |
| `settings.PARSEKIT_* / GLMOCR_*` | 文档解析管线 | ❌ 不放（属于解析，非结构化抽取；后续如需可另设“解析配置”） |
| `settings.TERM_*` | 术语集同步 | ❌ 不放（属于术语集模块） |
| `extraction_config_service.SCRIPT_TIMEOUT / MAX_OUTPUT / MAX_TERM_ROWS` | 脚本执行安全常量 | ✅ 建议（kb_tool：script_timeout 等） |
| LLM 端点/模型（尚未实现） | 未来“资源与配置” | ❌ 不放全局配置（对齐原项目分层：端点放资源，参数放全局） |
| rerank 模型（尚未实现） | 仅预留接口 | ⚠️ 建议预留 `reranker.enabled/model/top_n` 字段，实现后再启用 |

## 5. 建议：当前项目结构化抽取全局配置模型

采用“KB 级 JSON + 默认值合并”的方式（建议先宽松默认、再按需开启原项目式严格校验，避免新用户一进系统被强制填满）。

```json
{
  "retrieval": {
    "top_k": 10,
    "candidate_mult": 2,
    "weights": { "title": 0.2, "content": 0.8 },
    "default_confidence_threshold": 0.35,
    "context_top_k": 20,
    "context_max_tokens": 28000,
    "context": { "chars_per_token": 1.5, "min_keep_chars": 200, "truncate_marker": "\n[...内容截断...]" },
    "category_recall": { "top_k": 5, "per_dim_top_k": 10 },
    "query_embed": { "content_max_chars": 2000, "dedupe_similarity_threshold": 0.85 },
    "hybrid": { "enabled": true, "rrf_k": 60, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 1 },
    "reranker": { "enabled": false, "model": "", "top_n": 15 }
  },
  "llm": {
    "engine": "BaseExtract",
    "engines": {
      "BaseExtract": {
        "temperature": 0.0, "top_p": 0.1, "top_k": 20, "max_tokens": 32768, "timeout": 300, "enable_thinking": false,
        "concurrency": { "max_concurrency": 24, "cross_category": 24, "within_category": 1 },
        "batch": { "single_threshold": 8000, "batch_chars": 6000, "overlap": 500, "context_truncate": 32000 }
      },
      "LangExtract": {
        "temperature": 0.0, "top_p": 0.1, "top_k": 20, "max_tokens": 32768, "timeout": 300, "enable_thinking": false,
        "format_type": "JSON", "fence_output": false, "max_examples": 3, "passes": 2,
        "context_window_chars": 28000, "max_char_buffer": 40000,
        "concurrency": { "max_concurrency": 24, "cross_category": 8, "within_category": 3 }
      }
    }
  },
  "kb_tool": {
    "embed_batch_size": 16,
    "search_concurrency": 10,
    "semantic_top_k": 5,
    "match_top_k": 1,
    "match_threshold": 0.9,
    "script_timeout": 10,
    "script_max_output_bytes": 1048576,
    "script_max_term_rows": 1000
  }
}
```

说明：
- `retrieval` 与当前 `settings.RETRIEVAL_*` 一一对应，落地时服务优先读 KB 全局配置，缺省回退 `settings`。
- `llm` 与当前 LLM 兼容体系（LightRAG 风格 `llm_model_func/kwargs`）对接；端点（api_base/model）仍在“资源与配置”。
- `kb_tool` 直接接管 `extraction_config_service.py` 的脚本执行常量，避免硬编码。
- 类别级 `top_k / confidence_threshold / rerank_top_k / max_tokens` 已在 Schema 类别中可覆盖，全局值作为默认值（对齐原项目层级）。

## 6. 边界（不建议放入全局配置）

- 系统/基础设施：PostgreSQL、Redis、MinIO、JWT、任务队列、存储驱动。
- 文档解析管线：渲染 DPI、版面模型路径/置信度、OCR 服务地址/超时、页眉页脚、中间产物保留。
- 嵌入底层：模型权重路径、device/fp16/维度（这些属于部署资源；仅查询编码参数可进全局）。
- 术语集同步、审计、安全策略。
- 版本管理（建议单独模块，与全局配置配套但独立）。

## 7. 落地建议

1. 阶段一：新建 `kb_extraction_config`（或复用现有 extraction 表结构）存储 KB 全局配置，提供 `GET/PUT /kb/{kb_id}/extraction-config/global`，前端“全局配置”页签按三大区块实现（先做 `retrieval` + `kb_tool`，`llm` 待 LLM 链路接入后启用）。
2. 阶段二：检索/BM25/脚本服务改造为“全局配置优先、settings 兜底”，保持向后兼容。
3. 阶段三：LLM 抽取链路接入后，启用 `llm` 区块与引擎切换；再评估是否需要原项目式“提交前全量显式校验”（默认先宽松，避免阻塞）。
4. 版本管理：与全局配置同一版本号，保存即 +1，支持快照/回滚（记录项）。


> 注：落地实现中已将 `phase2` 命名为 `category_recall`（UI 展示“类别召回”），并移除 `type_query`（当前项目为 dense(title/content)+BM25，无 type 维度）。
