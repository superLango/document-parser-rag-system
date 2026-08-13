# 结构化抽取全局配置 · 阶段实施计划

> 依据：[EXTRACTION_GLOBAL_CONFIG_RESEARCH.md](EXTRACTION_GLOBAL_CONFIG_RESEARCH.md)
> 范围：仅结构化抽取全局配置（检索召回/LLM 抽取参数/脚本工具），不含系统级配置。
> 状态：**已实施完成（2026-08-13）**，P1-P4 全部落地并通过回归。

## 1. 阶段划分

| 阶段 | 内容 | 验收 |
|------|------|------|
| P1 后端底座 | 015 迁移（kb_extraction_config 表 + RLS）、模型、Schema、默认配置、GET/PUT 端点 | 五层测试（L1 默认/合并，L2 读写/版本，L4 非法值/越权，L5 隔离） |
| P2 前端页面 | “全局配置”页签 + 三大可折叠区块 UI，viewer 只读 | E2E 入口→编辑→保存→重载持久化→移动端 |
| P3 消费接线 | kb_tool 脚本超时/输出上限/术语集行数优先读全局配置；检索参数预留 | 脚本运行行为与全局配置一致；检索接线文档化 |
| P4 回归交付 | M34/M33 全量 + E2E 全量 + 覆盖率表 + 提交推送 | 全部通过 |

## 2. 归纳后的配置项（最终范围）

### 2.1 retrieval（检索召回与上下文）
top_k、candidate_mult、weights.title/content、default_confidence_threshold、
context_top_k、context_max_tokens、context.chars_per_token/min_keep_chars/truncate_marker、
category_recall.top_k/per_dim_top_k、query_embed.content_max_chars/dedupe_similarity_threshold（术语集精简去重阈值；精简开关与条目上限在 Schema 类别 Query 术语集中按类别配置）、
hybrid.enabled/rrf_k/dense_weight/keyword_weight/keyword_min_hits、
reranker.enabled/model/top_n（预留）。

### 2.2 llm（抽取引擎参数）
engine、engines.BaseExtract（temperature/top_p/top_k/max_tokens/timeout/enable_thinking/
concurrency.max_concurrency/cross_category/within_category/batch.single_threshold/batch_chars/overlap/context_truncate）、
engines.LangExtract（同上 + format_type/fence_output/max_examples/passes/context_window_chars/max_char_buffer）。

### 2.3 kb_tool（脚本工具性能与安全）
embed_batch_size、search_concurrency、semantic_top_k、match_top_k、match_threshold、
script_timeout、script_max_output_bytes、script_max_term_rows。

## 3. UI 布局设计（浅绿白主题）

- 入口：抽取配置页新增第一个页签“全局配置”（Settings2 图标），默认选中（对齐原项目）。
- 顶部：说明文字 + 右上“保存全局配置”按钮（viewer 隐藏）。
- 三个可折叠区块卡片（默认全部展开？建议默认折叠第一、三个，LLM 折叠，缩短页面）：
  1. **检索召回与上下文**：蓝色调图标 Search；分组“召回参数 / 上下文组装 / Phase 2 类别召回 / 五维 Query 编码 / 混合检索（hybrid）/ 重排序（reranker）”。
  2. **LLM 抽取参数**：紫色调图标 Cpu；引擎下拉（BaseExtract/LangExtract）+ 引擎专属参数 + 并发 + 分批/强约束参数。
  3. **脚本工具 kb_tool**：绿色调图标 Wand2；embed 分批、检索/匹配并发、semantic top_k、match top_k/阈值、脚本超时/输出上限/术语集行数。
- 表单元素：Input(type=number/text)、Switch、Select、Badge；每项带说明文案。
- 交互：保存后 toast；重载回显；viewer 全部禁用。

## 4. 数据与接口

- 表：`kb_extraction_config`（kb_id 唯一、enabled、content JSONB、version，RLS：select=成员，写=owner/admin/editor）。
- 接口：`GET/PUT /api/v1/kb/{kb_id}/extraction-config/global`（GET 成员 / PUT editor+，audit）。
- 存储策略：保存完整合并后的 content；读取时默认值 + 用户覆盖 deep merge；version 每次保存 +1。
- 消费：`run_script` 读取 kb_tool 配置；检索服务后续阶段接入（settings 兜底）。

## 5. 测试计划

- L1：默认配置结构、merge 覆盖、Schema 校验。
- L2：GET 默认 → PUT → GET 持久化/版本自增。
- L3：E2E 全流程（真实入口进入、编辑、保存、重载）。
- L4：非法数值/未知字段、超大 content、viewer 写拒绝、跨 KB 隔离。
- L5：viewer 只读、非成员 403、跨 KB 数据隔离。
