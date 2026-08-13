# 结构化抽取 · 设计实施方案（当前项目为主，原项目为参考）

- 日期：2026-08-13
- 目标：在 OCR/入向量之后，将当前项目已完成的 Schema / Prompt / 规则 / 脚本 / 全局配置
  串联成完整结构化抽取链路，并完成前端抽取页面与后端集成。
- 原则：以当前项目架构为主（PostgreSQL + RLS、现有任务/队列、现有检索服务、现有配置模块），
  原项目仅作为流程与交互参考，不照搬代码。

## 1. 原项目链路调研结论

### 1.1 抽取触发入口

- 文档完成 OCR + 索引（`document.status == completed`）后，在“结构化抽取”页点击“抽取”。
- `POST /kbs/{kb_id}/extraction/` 创建 arq 任务；`extraction_tasks.extract_document_impl`
  校验文档状态 → 进度回调（10 开始 → 35 类别构建 → 40 开始类别抽取 → 85 抽取完成 → 90 保存 → 100 完成）。
- 结果写入 `document.structured_data`（latest_result + records + history ≤50）+ 任务目录 JSON 文件。
- 证据：`document-parser-rag-system/backend/app/tasks/extraction_tasks.py`、
  `backend/app/api/v1/endpoints/kb_extraction.py`。

### 1.2 配置如何被“串起来”

`ExtractionConfigResolver.resolve(kb_id)` 一次性聚合：

```
kb_extraction_config(global: retrieval/llm/kb_tool)
  + prompt_templates(按类别 user_prompt)
  + rules/validation(脚本规则，按 stage/scope)
  + schema_templates(类别/字段/query_sources/term_base 展开)
  + term_bindings(术语集绑定)
  → ExtractionDomainConfig(cfg)
```

流水线 `extraction_pipeline.run` 依次消费：

1. **类别构建（category_builder）**
   - 遍历启用 Schema 模板的启用类别（`extraction_strategy != never`）；
   - `name_source=term_base` 的类别按术语集字段值循环展开成多个类别实例；
   - query = `fixed_query` + Query 术语集（主/精简、去重）；
   - 批量编码 query → 并发 hybrid_search（稠密五维 + BM25）→ 置信度过滤（全局阈值 + 类别级覆盖 + 词法兜底）→ 构建 `ExtractionTarget` + 类别 schema。
2. **类别检索（retrieval_service）**
   - per_dim_top_k / weights / top_k（类别级覆盖全局）→ hybrid_search；
   - 可选 reranker 重排 → context_assembler 按 `context_max_tokens` 拼接 → 动态白名单 prompt。
3. **Prompt 渲染（config_prompt_renderer）**
   - 按 `prompt_for_category(template_id, category_id)` 精确取 Prompt；
   - 替换 `${feature/context/schema/return_type/字段/字段.属性/术语集.字段}`，术语集数据预加载。
4. **LLM 抽取（extractor_factory + BaseExtract/LangExtract）**
   - 引擎由 `llm.engine` 决定；BaseExtract 支持长文本分批（batch 参数）；
   - JSON 输出解析 → `ExtractedRecord`；LangExtract 多轮/示例约束；
   - 运行时异常返回空类别（业务异常上报，不回退）。
5. **后处理与校验（script_manager）**
   - 按类别 `post` 脚本全权处理记录（移除/改写），`validation` 脚本校验；
   - 脚本经受限执行器（超时 kb_tool.script_timeout），可注入术语集只读数据。
6. **结果落库**
   - `result_writer` 保存 JSON；任务回写 `document.structured_data`（latest + history）。

### 1.3 前端页面

- `Extraction.vue`：可抽取文档列表（历史次数 + 抽取/历史按钮）、抽取历史对话框。
- `ExtractionDetail.vue`：Schema 信息卡；结果页“表格视图 / JSON 视图”切换；
  表格按类别父行展开动态表头记录；缺失字段提示；历史版本回看。
- 证据：`document-parser-rag-system/frontend/src/views/Kb/Extraction.vue`、
  `ExtractionDetail.vue`。

## 2. 当前项目 vs 原项目差异

| 维度 | 原项目 | 当前项目 | 影响 |
|------|--------|----------|------|
| 配置存储 | kb_extraction_config + schema_configs 通用节点 | 独立表：schema_templates/categories/fields、prompt_templates/content、rule_groups/items、kb_scripts、kb_extraction_config | 解析器需按当前模型重写，字段名不同 |
| 向量检索 | Milvus 五维（path/title/content/type/structural） | pgvector dense(title+content) + jieba BM25 + RRF（`retrieval_service.search`） | 类别召回改为双路检索 + RRF，无五维 |
| 类别召回 | 五维 query 编码 + 置信度过滤 | 需基于现有 `search` + 类别 query（fixed_query + query_sources）实现 | 新增 category_builder 适配层 |
| LLM 接入 | kb.config 读取 vLLM 端点 | 尚无 LLM 兼容层（D6 未落地） | 需新增 LLMClient + OpenAICompatibleClient（参考 LightRAG） |
| 任务队列 | arq + document.structured_data | arq/sync + TaskOutbox/DocumentTask（parse/index） | 新增 extraction 任务类型与结果表 |
| 结果存储 | document JSON + 任务目录文件 | 建议 PG 表（RLS） | 结果可检索/审计/导出 |
| 前端 | Extraction / ExtractionDetail 双页 | 结构化抽取为占位页 | 新建两个页面并接路由 |
| 全局配置 | 检索/LLM/kb_tool 全量 | 已实现 retrieval/llm/kb_tool（部分预留） | 检索接线待 P3 落地 |

## 3. 目标链路（当前项目）

```
文档完成解析 + 索引（document.status=completed, index_status=completed）
        │ POST /kb/{id}/extraction/{document_id}（editor+）
        ▼
Outbox(type=document_extraction) → arq/sync
        ▼
ExtractionPipeline.run
  1) Resolver：Schema模板(启用类别/字段/query_sources) + Prompt(按类别)
     + 规则组(按类别脚本) + 全局配置 + 术语集
  2) CategoryBuilder：类别展开(term_base 循环) → query 组装(fixed_query+术语集)
     → 现有 retrieval_service.search(dense+BM25+RRF, top_k/阈值) → 置信度过滤
  3) PerCategory：检索 → 上下文组装(context_max_tokens) → Prompt 渲染
     → LLMClient(EXTRACT 角色) → JSON 解析
  4) 后处理/校验脚本（现有 KbScript 受限执行）
  5) 结果落库 extraction_results(kb_id, document_id, schema_id, version, categories)
     + documents.extraction_status + history
        ▼
GET result / status / history / export
```

## 4. 后端集成设计

### 4.1 数据模型（迁移 016_extraction_result）

- `extraction_results`：id、kb_id(RLS)、document_id、schema_template_id、status(queued/running/completed/failed)、
  progress、categories JSONB（[{category_id, category_name, records[], rejected[], missing_fields[]}]）、
  summary JSONB、timing JSONB、error JSONB、version、created_at/updated_at。
- `documents` 增加 `extraction_status`（nullable：未抽取/completed/failed）。
- 任务：`TaskOutbox.type` 新增 `document_extraction`；`DocumentTask.type` 新增 `document_extraction`；
  sync 执行器扩展分支（开发模式）。
- 历史：同一文档重复抽取时旧结果 `history JSONB`（≤50），或独立 `extraction_history` 表（推荐表）。

### 4.2 配置解析器（services/extraction/extraction_resolver.py）

- 输入当前配置表，输出 `ExtractionDomainConfig`：
  - `schema_templates`：启用模板 → 类别（name_source/term_base、fixed_query、query_sources、字段、类别级 top_k/阈值/max_tokens/strategy）；
  - `prompt_templates`：按模板绑定类别 → system/user；
  - `rule_groups`：按类别解析 post/validation 脚本（script_id → name/code/description）；
  - `global`：`get_global_config`（retrieval/llm/kb_tool）；
  - `term_bases`：名称来源/Query 术语集数据（只读注入）。
- 复用 `extraction_config_service` 现有查询，不重复建表。

### 4.3 LLM 兼容层（services/llm/llm_client.py）

- `LLMClient.complete(messages, *, json_mode, temperature, max_tokens, timeout)`；
- `OpenAICompatibleClient`（vLLM/Ollama 兼容，参考 `lightrag/lightrag/llm/openai_compatible.py` 适配思想）；
- 端点来源：**先做 KB“资源与配置”LLM 服务表单**——扩展 KB 配置 `services.llm_vllm`（api_base / model / api_key / 连接测试），
  抽取流水线从该配置读取端点；参数（温度/并发/分批/超时）来自全局 `llm` 区块。

### 4.4 抽取流水线（services/extraction/extraction_pipeline.py）

按第 3 节链路实现，与当前项目对齐的关键点：
- 类别召回不引入五维：query = feature 名 + fixed_query + query_sources 值（主/精简、去重阈值），
  走 `retrieval_service.search`（dense title+content + BM25 + RRF，top_k/阈值来自全局+类别级）；
- 上下文组装：按 `context_top_k` / `context_max_tokens` / `chars_per_token` / 截断标记；
- Prompt 渲染：移植前端 PromptEditor “测试组装” 的占位符引擎（${feature/context/schema/return_type/字段/字段.属性/术语集.字段}）；
- JSON 解析：LLM 返回 JSON/围栏剥离 → 按类别 schema 校验字段类型/必填 → 缺失字段记录；
- 脚本后处理/校验：复用现有受限执行器（子进程 -I、超时/输出上限/术语集注入），按规则组 stage 执行；
- 结果对象：类别 → records/rejected/missing_fields/summary/timing。

### 4.5 端点（/kb/{kb_id}/extraction）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /documents | viewer+ | 已完成解析+索引的可抽取文档列表（含 extraction_status/history_count） |
| POST | /{document_id} | editor+ | 启动结构化抽取（幂等：进行中 409，已完成可 re-extract 新版本） |
| GET | /{document_id}/status | viewer+ | 任务状态/进度/阶段消息 |
| GET | /{document_id}/result | viewer+ | 最新抽取结果（categories/records/summary） |
| GET | /{document_id}/history | viewer+ | 历史版本列表/详情 |
| GET | /export?document_id= | viewer+ | CSV/XLSX 导出（对齐原项目） |
| DELETE | /{document_id}/result | editor+ | 删除该文档最新结果与全部历史（硬删，审计；确认项 B13） |

### 4.6 队列与状态机

- `queued → category_build(10) → retrieving(20) → extracting(60) → post_processing(80) → completed/failed`；
- **失败不自动重试（确认项 B11）**：任务直接 `failed` 并记录错误信息；用户通过详情页“重新抽取”按钮重新发起（幂等：进行中拒绝）；死信记录保留供排查；
- 并发：LLM 总并发（全局 llm.concurrency.max_concurrency）+ 类别间并发（cross_category）信号量；
- 开发模式（TASK_EXECUTOR=sync）同步执行，保证本地闭环。

## 5. 前端页面设计（结构与交互按原系统，风格按当前项目主题）

> 对齐原则：页面结构、操作路径、交互细节与原系统 `Extraction.vue` / `ExtractionDetail.vue` 一致；
> 视觉风格使用当前项目浅绿白主题 token（UI_THEME.md），不照搬原系统的蓝色/紫色点缀与玻璃拟态。

### 5.1 抽取列表页（KbStructuredExtractionPage，替换占位）

- PageHeader：标题“结构化抽取”、描述“知识库：{名称}”；右上角保留 **RLS 隔离** 徽标与 **刷新** 按钮（对齐原系统）。
- 文档列表 Card：加载骨架 → 空态（“无可抽取文档 / 请先上传文档并完成 OCR 解析”）→ 行内布局：
  文件图标块 / 文件名 + 解析状态徽标（已解析/解析中）+ 已抽取成功对勾 / 元信息（文件大小 · 字符数 · 最新 Schema 名 · N 个历史版本）/ 时间 / 操作按钮 **历史**（无结果时禁用）+ **抽取**。
- 点击“抽取”→ 进入详情页（不自动开始，由用户在详情页选 Schema 后开始）。
- 点击“历史”→ 弹出抽取历史对话框（文件名头、骨架、空态、版本列表：Schema 名 + “最新”徽标 + 抽取时间）。
- 交互动画：行 hover 高亮/图标放大/左侧竖条展开等按当前主题实现，保留原系统交互意图。

### 5.2 抽取详情页（KbExtractionDetailPage，路由 /kb/:id/extraction/:documentId）

- **全屏双栏布局**（对齐原系统）：
  - 顶部 sticky header：返回列表、文档名 + 解析状态徽标、查看历史版本时显示“历史版本”徽标、右上“历史记录”按钮。
  - 左栏：**原始文档预览**（PDF 用现有 PdfViewer，非 PDF 显示不支持提示）。
  - 右栏：
    1. **选择抽取 Schema**：卡片网格（名称 / N 类别 / N 字段 / 描述 / 选中对勾），抽取进行中禁止切换；
    2. **开始抽取 / 重新抽取**按钮（未选 Schema / 进行中 / 加载中禁用；进行中显示“抽取中...”，已完成或失败后显示“重新抽取”并允许再次发起）；
    3. **进度卡**：状态图标 + 进度文案 + Schema 信息、百分比、进度条、**四步流程条（初始化 → 解析文档 → 抽取字段 → 完成）**；
    4. **抽取结果卡**：空态 / 抽取中动画 / 结果区；
       - 右上 **表格视图 / JSON 视图** 切换；
       - 表格视图：类别父行（chevron 旋转、类别名、N 条记录、N 字段）→ 展开动态表头记录表；
       - JSON 视图：格式化 `<pre>`；
       - **缺失字段提示卡**（warning 色，Badge 列表）。
- 进度：**2 秒轮询任务状态**；退出重进后通过 localStorage + 任务列表回退恢复轮询（对齐原系统）。
- 历史记录对话框：版本列表（Schema 名、“最新”徽标、N 个字段、抽取时间），**点击版本回看该结果**并关闭对话框（header 显示“历史版本”徽标）。
- 交互细节全部按原系统保留：轮询恢复、运行中禁止切 Schema、类别展开、视图切换、历史回看。

### 5.3 路由与菜单

- `/kb/:id/extraction` → 列表；`/kb/:id/extraction/:documentId` → 详情；
- 现有侧栏“结构化抽取”入口指向列表页；返回按钮回列表。

## 6. 分阶段实施计划

| 阶段 | 内容 | 验收 |
|------|------|------|
| E1 数据与任务底座 | 016 迁移（extraction_results + documents.extraction_status + history）、任务类型/Outbox、sync 执行器分支 | 迁移/模型/任务状态机测试 ✅ **已完成（2026-08-13，12/12）** |
| E2 配置解析与 LLM 层 | ExtractionDomainConfig 解析器、LLMClient/OpenAICompatibleClient、**KB 资源与配置 LLM 服务表单**（services.llm_vllm + 连接测试） | 单元测试（解析完整性、LLM 客户端 mock、资源配置读写） |
| E3 抽取流水线 | CategoryBuilder、上下文组装、Prompt 渲染、LLM 抽取、JSON 解析、脚本后处理/校验 | 集成测试（真实 mock LLM + 术语集 + 脚本） |
| E4 端点与任务 | extraction 端点（列表/启动/状态/结果/历史/导出/**删除结果与历史**）+ arq/sync 任务（失败不重试）+ 进度轮询 | API 五层测试 + 并发用例 |
| E5 前端页面 | 列表页 + 详情页 + 路由 + 轮询进度 + 表格/JSON/历史/导出/删除 + **重新抽取** | E2E 页面闭环（入口→抽取→进度→结果→返回） |
| E6 整体回归 | M34/M33/抽取全量 + E2E + 覆盖率表 + 文档更新 | 全部通过 |

## 7. 测试计划（铁律）

- L1：解析器默认/合并、Prompt 占位符渲染、JSON 解析边界（围栏/空/类型错）。
- L2：任务状态机（outbox→running→completed/failed）、结果落库、历史版本、同步执行器。
- L3：API 全流程（列表→启动→进度→结果→导出）+ E2E 页面闭环。
- L4：非法文档状态启动 409、重复启动幂等、结果超限、脚本超时/输出上限、断点重试。
- L5：viewer 只读、非成员 403、跨 KB 结果隔离（RLS）。
- 并发：多文档同时抽取、同文档并发启动、LLM 信号量限流。

## 8. 确认清单（已确认，2026-08-13）

- A1-A6：**全部按推荐**——前端结构与交互按原系统，视觉用当前浅绿白主题。
- B7：**先做 KB“资源与配置” LLM 服务表单**（services.llm_vllm：api_base/model/api_key + 连接测试），抽取端点从该配置读取。
- B8：结果存储用**独立 `extraction_results` 表 + 历史表**。
- B9：进度用**轮询（2s）**。
- B10：导出 **CSV 先行，XLSX 后续**。
- B11：失败**不自动重试**，直接提示失败；提供**重新抽取**按钮。
- B12：历史保留 **50 条**。
- B13：**提供删除**最新结果与全部历史入口（editor+，审计）。
- B14：可抽取条件 = 解析 completed 且索引 completed。
- B15：类别召回见第 9 节详细说明；**演进路径已确认**：第一版全量参与（零命中剔除、阈值预留）→ 第二版命中原因记录与阈值统计 → 第三版类别召回模式（严格/宽松/关闭），终态对齐原项目“提前剔除”。




## 9. B15 详情：原项目类别召回机制与当前/后续优化

### 9.1 原项目类别召回（Phase 2 category_builder）做了什么

1. **类别来源与展开**
   - 遍历启用 Schema 模板 → 启用类别（`extraction_strategy != never`）；
   - `name_source=term_base` 的类别按术语集字段值循环展开成多个“类别实例”（如牌号类别按牌号表展开为每个牌号一个实例）；
   - 每个实例生成 `ExtractionTarget`：feature（类别名/术语值）、category_id、template_id、query_mode、fixed_query、query_sources、top_k、rerank_top_k、confidence_threshold、fields。
2. **Query 组装与编码**
   - query = 类别名 + fixed_query + Query 术语集（label/group_field/value_field，主/精简、去重阈值）；
   - 五维 query 编码（path/title/content/type/structural）→ 每类别并发 `hybrid_search`（top_k=5）；
   - 混合检索开启时再跑稀疏 BM25 词法兜底检索。
3. **置信度过滤（feature_filter）**
   - 全局 `default_confidence_threshold` + 类别级 `confidence_threshold` 覆盖；
   - 稠密分不足但词法命中 ≥ `keyword_min_hits` 的类别保留（强词法信号类别兜底，如化学成分）；
   - 保留的类别再构建“类别 schema”，进入后续检索 + LLM 抽取。
4. **目的与代价**
   - 目的：判断“文档里到底有哪些类别”，避免对全部类别都做 LLM 抽取（省 token/时间），同时不误杀词法强信号类别；
   - 代价：五维编码重、阈值依赖稠密分、term_base 大库可能展开出大量实例、阈值需要人工调优。

### 9.2 当前项目的差异

- 检索是 dense（title+content 双向量）+ jieba BM25 + RRF，无五维；
- 全局配置已含 `category_recall.top_k/per_dim_top_k`、`default_confidence_threshold`、`hybrid.keyword_min_hits`（预留）；
- 类别级 top_k / confidence_threshold / rerank_top_k / max_tokens 已在 Schema 类别中可配置。

### 9.3 首个版本方案（已确认）

- 全部启用类别都参与：遍历启用模板的启用类别；term_base 类别按术语集字段展开为实例；
- 每类别组装 query（feature + fixed_query + query_sources 主/精简、去重阈值）→ 调现有 `retrieval_service.search` 对当前文档检索；
- 过滤规则：**零命中剔除**（无候选/分数为 0）；`confidence_threshold` 本期预留（可写入结果 summary，不强制剔除）；
- 类别级 top_k / max_tokens 继续生效（控制上下文与输出规模）。

### 9.4 后续版本优化方向

1. 置信度阈值渐进启用：全局默认 + 类别级覆盖 + 词法兜底（keyword_min_hits），先提供“仅提示不剔除”模式，用真实样本调参后再切换为“剔除模式”。
2. term_base 展开治理：大术语集分页/缓存、按 group_field 聚合、展开实例数上限保护（防几千个实例打爆）。
3. 两阶段 Query 精简：主查询 + 精简查询合并（去重阈值、主/精简上限已配置），预留 LLM Query 改写（问题优化）可选。
4. 召回反馈闭环：被剔除类别及原因（零命中/置信度低/词法不足）写入结果 summary，前端展示 skipped 原因，辅助调配置。
5. 评估驱动调参：复用评测 CLI 思路，对 top_k/阈值/权重做 A/B 复测，避免凭感觉调参。
6. 动态白名单：从术语集构建类别级白名单注入 Prompt（原项目已有），首版先保留字段级白名单。
7. 命中溯源：返回类别命中的块路径/页码，前端可与文档查看器联动跳转原文。


### 9.5 结论与演进路径（已确认，2026-08-13）

结论：第一版采用“全量参与、零命中剔除、阈值预留”比直接照搬原项目“提前剔除”更稳妥；
原项目的提前剔除是终态方向，二者不是二选一，而是同一能力的演进阶段。

演进路径：

| 版本 | 召回策略 | 说明 |
|------|----------|------|
| 第一版 | 全部启用类别参与，零命中剔除，confidence_threshold 仅记录不强制 | 先跑通链路、拿到真实结果与命中分数 |
| 第二版 | 结果记录每类别命中分数/剔除原因（零命中/置信度低/词法不足），评测样本统计阈值分布 | 用数据调参，不拍脑袋 |
| 第三版 | 增加“类别召回模式”配置（严格/宽松/关闭，KB 级可选） | 终态对齐原项目提前剔除，阈值由评测驱动 |

前端配套：第二版在结果 summary 展示 skipped 原因，辅助配置调优；第三版在全局配置增加“类别召回模式”开关。
