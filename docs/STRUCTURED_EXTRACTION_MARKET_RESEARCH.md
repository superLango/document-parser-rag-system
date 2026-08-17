# 市面成熟文档「结构化抽取阶段」调研与对比（2026-08）

> 范围界定：本调研**只对比抽取阶段**（输入：已解析的文本/结构化文档；输出：Schema 约束的结构化字段），
> **不对比解析/OCR 阶段**（版面、OCR、表格还原等见 `DOCUMENT_EXTRACTION_MARKET_RESEARCH.md`）。
>
> 本系统抽取阶段现状（以源码为准）：
> `backend/app/services/extraction/` 下 类别构建（category_builder）→ 类别召回（BGE-M3+BM25）→
> 上下文组装（context_assembler，不截断）→ LLM 抽取（BaseExtract / LangExtractPkg 原包，分段多次抽取不截断）→
> 脚本后处理/校验（script_processor）→ 结果存储（result_store，最新+历史 50 条）。

## 1. 调研对象与「抽取阶段」设计

| 系统/框架 | 抽取阶段核心设计 |
|---|---|
| Azure Document Intelligence（自定义抽取） | 双路线：**custom template**（标注训练、依赖固定版式、快、可解释）与 **custom neural**（深度学习、容忍版式变化、支持 overlapping fields）；**字段级置信度**，表格行列/单元格置信度（2024-02-29-preview 起）；官方建议高精度场景接入 **human review** |
| Google Document AI（Custom Extractor） | Schema 定义实体类型（entity types、occurrence、checkbox/tabular labels）；**基础模型开箱即用 + 标注数据增强**；每个实体带 **0-1 置信度**，可用置信度阈值决定是否转人工 |
| AWS Textract | **Queries 查询式抽取**：自然语言提问（同步最多 15 问、异步 30 问），返回问题-答案对；另有 FORMS（key-value）与 TABLES 特征；答案倾向使用文档原文词 |
| 合合 TextIn（DocFlow/xParse） | 自研垂直领域语义模型、免标注开箱即用；官方实践文章明确建议**「先切块再按模块定义输入输出」，不要全文直抽**；内嵌规则配置（金额上限、字段缺漏、单位不符、时间越限）自动判高风险并触发人工复核；输出带**溯源信息（页码、路径、坐标）**，标题层级驱动分块 |
| Rossum | **置信度阈值自动化**：Confident 模式默认字段阈值 0.975，可按队列/字段调整；内置 checksum 校验（如 VAT 税率、净额/总额勾稽）；每条校验来源记入 `validation_source`；低于阈值或校验失败进入人工 review 队列 |
| Hyperscience | 流水线每步 **confidence 低于阈值转 Supervision（人工）**；transcription 模型从人工修正中学习；支持 QA 采样抽检 |
| ABBYY Vantage | **Rule verification**：内置规则可校验、修改、计算字段值（如 checksum 求和），失败路由人工 review |
| Docling pipelines / docling-graph | Pydantic 模板即 Schema 契约；LiteLLM 100+ 供应商；**staged 抽取**（多 pass 优化 ID 发现/父链接）与 **delta 抽取**（chunk 级增量，IR 归一化后按 (path, identity) 合并去重，resolver 合并近似重复实体） |
| LangExtract（Google，我们已用原包） | 五阶段：pre-flight（校验 few-shot 与源文本可对齐）→ 模型解析 → Prompt 生成 → LLM 推理 → **解析与对齐**（exact/fuzzy 0.75/lesser 三种匹配方式把抽取值锚定回源文本区间）；`max_char_buffer` 分块 + batch；multi-pass（first-pass wins 合并） |
| Instructor / Outlines / PydanticAI | Instructor：Pydantic 校验失败自动把错误回传 LLM 重试（默认 3 次）；Outlines：FSM 约束解码，结构合法零解析错误、本地 vLLM 支持、开销 5-10%；PydanticAI：Agent 框架 + retries + 依赖注入 |
| LlamaParse Extract / LlamaExtract | 三步：Schema 定义（UI 或 JSON，含字段类型/约束/extraction rules）→ 抽取 → JSON 输出；Schema 可从候选文档推断 |
| Extend.ai | 抽取结果的**字段级溯源**：每个字段附带原文 bbox/坐标/文本区域（citations & reasoning） |
| MLJAR（批量抽取实践） | 长文档重叠分块独立抽取，**合并时每个字段取「信号最清晰」的 chunk 值**（merge by clearest signal） |

## 2. 与本系统抽取链路逐环节对比

| 环节 | 本系统现状 | 对方做法 | 差距/对方优点 |
|---|---|---|---|
| Schema/目标定义 | Schema 模板（categories→fields）+ Prompt 模板 + 术语集展开（EXPAND_LIMIT=200）；类别级 top_k/max_tokens/阈值 | Azure template/neural 标注训练；Google 实体类型+occurrence；LlamaParse UI/JSON schema+extraction rules | 我们已具备 Schema 驱动；缺「标注训练数据」与「自然语言查询定义字段」两种低门槛路线 |
| 类别召回 | 固定 query + Query 术语集（主 30+精简 8，语义去重 0.85）→ BGE-M3+BM25 召回；loose/strict/off 三模式；零命中剔除 | 各家类似（向量/混合检索）；TextIn 强调**按业务模块切块后按模块抽取**，避免跨模块上下文污染 | 我们按「类别+query」召回，方向一致；上下文仍是「整文档命中块拼接」，无模块级边界 |
| 上下文组装 | 命中块按相关性拼接；max_tokens=None **不截断**，交给引擎分段多次抽取（batch_chars 默认 6000，overlap 500） | LangExtract max_char_buffer 分块+batch；MLJAR 重叠分块+clearest signal 合并；docling-graph delta 按 chunk 增量 | 我们分段是**字符窗口切分**，可能把同一表格/段落拆到两段；MLJAR「按字段取信号最清晰 chunk」的合并策略比「JSON 去重」更优 |
| 抽取执行 | BaseExtract 单轮/分段直抽；LangExtractPkg 原包（多 pass + resolver 对齐）；并发 8，类别间并发；段级 600s 超时 | LangExtract multi-pass first-pass wins；docling-graph staged（多 pass 优化 ID/父链）；Azure neural 自带表格行列置信度 | 我们已有原包多 pass；缺 **staged 两阶段（先找实体 ID 再补属性）** 与 **增量/delta 抽取** |
| 输出约束 | BaseExtract json_mode；LangExtractPkg output_schema（XGrammar）+ 默认关闭 fence | Instructor 校验重试、Outlines FSM 约束、PydanticAI retries | 已对齐（XGrammar 属最强约束）；可补 Instructor 式「校验失败重试回传错误」兜底 |
| 对齐/溯源 | **未实现**：记录仅有字段值，无原文区间/页码锚定 | LangExtract resolver（exact/fuzzy/lesser，字符区间）；TextIn 溯源（页码/路径/坐标）；Extend 字段级 bbox | **明显差距**：我们丢弃了「值来自哪一段原文」的证据，无法复核/审计/纠错定位 |
| 多值拆分 | few-shot 拆条示例 + 脚本后处理；dedupe 按 JSON 全等 | KNIME/TextIn 等均在 Prompt 或后处理做多值拆条；LangExtract attributes 保留字段关联 | 方向一致；缺「按字段语义去重+规范化」（如同值不同写法合并） |
| 字段级置信度 | **未实现**：仅类别命中分数与脚本 reject | Azure/Google/Rossum/Hyperscience 均有字段级置信度，并据此路由人工复核 | **明显差距**：当前无法区分「低可信需复核」与「高可信可直接入库」 |
| 校验规则 | 脚本（post/validation）+ missing_required_fields；reject 记录 | Rossum checksum/勾稽、ABBYY rule verification（校验/修改/计算）、TextIn 内嵌规则 | 我们脚本能力更强但**无内置校验算子库**（如金额勾稽、单位、时间越限） |
| 人工复核闭环 | **未实现**：结果只有抽取与历史，无复核/确认状态、无修正回流 | Rossum/Hyperscience/Azure/TextIn 均有 HITL：低置信转人工、修正后回灌训练/规则 | **明显差距**：企业内场景需要「抽取→复核→确认→修正回流」闭环 |
| 增量/演进 | 无增量：重跑即全量分段抽取 | docling-graph delta：chunk 级增量、按 identity 合并去重 | 差距：长文档重复抽取成本高 |
| 评估 | 自建测试脚本（qa/functional）+ 结果目录对比 | 各家以字段级精确率/召回评测；LLM judge | 可补字段级评估指标与 LLM judge |

## 3. 对方优点清单（聚焦抽取阶段，按可借鉴价值排序）

1. **字段级置信度 + 人工复核路由**（Azure/Google/Rossum/Hyperscience/TextIn）：每个字段带置信度，低于阈值进复核队列，修正结果回流（规则/示例），形成闭环。这是我们与商用 IDP 差距最大、对企业内部使用价值最高的一项。
2. **抽取值溯源/对齐**（LangExtract resolver、Extend bbox、TextIn 页码坐标）：记录每个值来自哪段原文（chunk_id+页码+片段或字符区间），支撑复核、审计与纠错定位。我们已有 chunk 命中信息但未随记录保留。
3. **校验规则算子化**（Rossum checksum、ABBYY rule verification、TextIn 内嵌规则）：除自定义脚本外提供内置算子（勾稽、单位、时间、范围、缺漏），低代码可配。
4. **按模块切块抽取**（TextIn 官方实践、MLJAR）：不要全文直抽；先按业务模块/章节切块，再对每个模块定义输入输出，避免跨模块上下文污染；合并时按字段取信号最清晰 chunk。
5. **Staged / Delta 抽取**（docling-graph）：先抽实体 ID 再补属性（staged），或按 chunk 增量抽取 + identity 合并去重（delta），降低长文档重复抽取成本。
6. **校验失败自动重试**（Instructor）：Pydantic 校验失败把错误回传 LLM 重试（默认 3 次）；可作 XGrammar 之外的兜底。
7. **低门槛字段定义**（Textract Queries 自然语言提问、LlamaExtract schema 推断、Azure 模板标注训练）：对非专业配置人员友好，可作为 Schema 之外的补充入口。
8. **批量合并策略**（LangExtract multi-pass first-pass wins、MLJAR clearest signal）：分段抽取结果合并时按字段择优，而非简单 JSON 去重。

## 4. 可借鉴项落地建议（映射到当前代码）

| 优先级 | 借鉴项 | 落地方式 | 涉及文件（当前项目） |
|---|---|---|---|
| P0 | 字段级置信度 + 未确认标记 | 引擎输出增加 `confidence`/`needs_review` 字段（Base 由模型输出或后验启发式，LangExtractPkg 由对齐质量推算）；结果页展示 | `backend/app/services/extraction/llm_extractor.py`、`lang_pkg_extractor.py`、`extraction_models.py`、`result_store.py`、前端抽取结果页 |
| P0 | 抽取值溯源 | 记录附加 `evidence`（chunk_id、source_pages、原文片段）；LangExtractPkg 已有 resolver 对齐结果可映射 | `lang_pkg_extractor.py`（对齐结果透传）、`extraction_models.py`、`result_store.py` |
| P0 | 校验规则算子库 | 在脚本后处理外增加内置校验算子（勾稽/单位/时间/范围/缺漏），前端可配置 | `backend/app/services/extraction/script_tools.py`、`script_processor.py`、抽取配置前端 |
| P1 | 人工复核闭环 | 抽取结果增加「复核/确认/驳回」状态与字段级修改，修正内容回流示例库/规则 | `result_store.py`（状态字段）、新增 review API、前端结果页 |
| P1 | 按模块切块抽取 | 上下文分段从「字符窗口」改为「按版面块/章节语义分组」，避免拆散同一表格；合并按字段择优 | `context_assembler.py`、`llm_extractor.py`、`lang_pkg_extractor.py` |
| P1 | 校验失败自动重试 | BaseExtract 增加「解析/必填校验失败回传错误重试 N 次」 | `llm_extractor.py` |
| P2 | Staged/Delta 抽取 | 长文档按版本 diff 只重抽变化块；或先抽实体再补属性两阶段 | `pipeline.py`、`category_builder.py` |
| P2 | 字段级评估 | 测试脚本增加字段级精确率/召回与 LLM judge 对比 | `qa/functional/`、`qa/evaluation/results/` |

## 5. 结论

- 我们的抽取主链路（Schema/术语集驱动 → 召回 → LLM 分段抽取 → 脚本校验）与主流方案方向一致，**输出约束（XGrammar）与脚本后处理不落后**；
- 对方最大优点集中在抽取阶段的四个闭环能力：**字段级置信度、抽取值溯源、校验算子化、人工复核回流**；其次是**按模块切块抽取、增量抽取、校验失败重试**；
- 建议优先落地 P0 三项（字段级置信度、溯源、校验算子库），它们直接提升企业内抽取结果的可信度与可复核性，且改造量可控。
