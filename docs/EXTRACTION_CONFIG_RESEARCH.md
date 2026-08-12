# 原项目抽取配置功能分析（基于前端源码调研）

> 调研对象：`document-parser-rag-system` main 分支
> 前端：`views/Kb/ExtractionConfig.vue`（2821 行）、`PromptEditor.vue`（740 行）、
>       `ScriptManager.vue`（534 行）、`api/modules/kb.ts`（抽取配置相关方法）
> 后端：`api/v1/endpoints/extraction_config.py`、`schema_templates.py`、`kb_extraction.py`
> 注意：main 分支缺 `app/models` 目录，模型字段为推断；本文以页面与接口行为为准。

## 1. 整体定位

抽取配置是知识库的**抽取策略配置中心（零代码/低代码）**，单页多页签：

| 页签 | 作用 |
|------|------|
| 全局配置 | 检索参数 + LLM 抽取引擎参数 + KB 工具参数 |
| Schema 模板 | 三层结构（模板→类别→字段），类别可联动术语集 |
| Prompt 模板 | 提示词模板（simple / 绑定 Schema），独立编辑页 |
| 后处理与校验规则 | 规则组按类别绑定脚本规则项 |
| 脚本管理 | 自定义后处理/校验脚本（脚本即函数 + 调试） |
| 版本管理 | 配置快照、diff、回滚、删除 |

权限：viewer 可查看，editor+ 可管理；数据隔离 `/kbs/{kb_id}/extraction-config`，RLS 强制。

## 2. 全局配置（global）

- **检索 retrieval**：
  - top_k / per_dim_top_k / 默认置信度阈值 0.35 / context_top_k / context_max_tokens
  - context 参数：chars_per_token、min_keep_chars、截断标记
  - phase2：top_k / per_dim_top_k
  - query_embed：content_max_chars、feature_repeat、embed_max_length、type_query、相似度去重阈值
  - 五维权重：path 0.15 / title 0.2 / content 0.45 / type 0.05 / structural 0.15
  - reranker：启用、model、top_n
  - hybrid：启用、dense_candidate_k、keyword_top_k、rrf_k、dense/keyword 权重、keyword_min_hits
- **LLM 引擎 llm**：engine 选择（BaseExtract / LangExtract），每引擎独立参数：
  - BaseExtract：temperature/top_p/top_k/max_tokens/timeout/enable_thinking、并发（max/cross/within）、批量（single_threshold/batch_chars/overlap/context_truncate）
  - LangExtract：额外 format_type、fence_output、max_examples、passes、context_window_chars、max_char_buffer
- **KB 工具 kb_tool**：embed_batch_size、search_concurrency、semantic_top_k、match_top_k、match_threshold、script_timeout
- 兼容旧结构：引擎名归一化（glmocr→BaseExtract、langextract→LangExtract），旧顶层 llm 参数并入对应引擎
- 交互：三大区块折叠面板，保存按钮；类别级参数可覆盖全局

## 3. Schema 模板（schema）

三层结构：模板 → 类别 → 字段。

### 3.1 模板
- 列表/新建/编辑/删除（confirm 提示级联删除）；启用开关、排序
- 模板含名称、描述、is_active、categories

### 3.2 类别（核心，术语集联动点）
- 名称来源 `name_source`：
  - `manual`：手动输入类别名称
  - `term_base`：**选择术语集 + 取值字段**，按该字段值循环生成类别；
    名称可为空，显示名自动取术语集名
- 描述、返回类型（array/object）、抽取策略（auto/always/never）
- 固定 Query 文本（fixed_query，如“标准名称 标准编号 文件编号”）
- **Query 术语集**（可多个）：
  - label（显示名，必填）、term_base_id、group_field（可选分组字段）、value_field（必填值字段）
  - in_query（参与 Query，开启后挂载到 Query 下方展示）
  - dedupe（精简去重）、query_main_limit（主查询上限，默认 30）、query_refined_limit（精简上限，默认 8）
  - 折叠/展开编辑，单独保存
- 类别级覆盖：confidence_threshold / top_k / rerank_top_k / max_tokens（留空用全局）
- 启用开关

### 3.3 字段
- 字段名、类型（string/number/boolean/array）、字段说明、示例（提升抽取精度）、必填、排序

### 术语集字段来源
- `effectiveFieldsOfTermBase`：api/db 术语集用 columns；manual 术语集用内置字段
  （term_name/standard_name/definition/category/synonyms/aliases/standard_number）
- 显示名优先 column_aliases 新表头名，value 用原始字段名

## 4. Prompt 模板（prompt）

### 4.1 列表页（ExtractionConfig 内）
- 模板 CRUD；新建：名称、描述、模式选择
  - `simple`：不绑定（单个 user 提示词）
  - `schema`：绑定 Schema 模板 + 勾选类别（默认全选，术语库类别带徽标）
- 启用开关；创建后进入编辑页

### 4.2 编辑页（PromptEditor.vue，独立路由）
- simple 模式：上部 system 提示词 + 下部 user 提示词
- schema 模式：上部 system + **三栏**（左类别列表 / 中当前类别 user 提示词 / 右可用字段）
  - 右侧字段支持 `${字段名}` / `${字段名.子属性}` 占位符插入
  - 系统参数占位符：`${feature}`、`${feature_descript}`、`${schema}`、`${context}`、`${return_type}`、`${prev_brands}`
  - 术语集参数：名称来源术语集 + Query 术语集自动并入右侧引用列表
- 保存：simple 传 system_prompt + user_prompt；schema 传 system_prompt + categories[]
- 内嵌 TestPanel 调试（可试跑）

## 5. 后处理与校验规则（rules）

- 规则组 CRUD（名称、启用、排序；删除 confirm 提示级联删除规则）
- 组内按类别绑定**规则项**：脚本名（script_name）+ 参数（JSON），启用开关；可移除
- 规则项来自脚本管理里的 post / validation 脚本
- 后端：rule-groups CRUD + saveRuleGroupItems（批量保存组内规则项）
- 另有 validation 与 bindings 接口（保存抽取校验配置与 Schema/字段绑定，页面在规则页签内使用）

## 6. 脚本管理（scripts）

`ScriptManager.vue`，**左中右 + 底部调试**布局：

- 左：脚本目录（post 抽取后处理 / validation 校验），目录下脚本列表 + 新建
- 中：脚本编辑（代码编辑器 + 名称/描述/启用/脏标记）
- 右：当前目录 IO 注册（输入参数/输出参数/可用工具目录/术语集列表），折叠面板
- 底部：调试区（传入 args JSON → 运行 → 展示结果）
- 脚本契约：`def run(args)` 返回 dict；post/validation 返回 `{"records": [...], "rejected": [...]}`
- 内置工具 kb_tools：embed / semantic_search / match_record / get_term_records（按术语集名称+字段取值）等
- 默认模板含示例注释（后处理/校验逻辑、术语集访问示例）

## 7. 版本管理（versions）

- 快照列表：名称、版本号、创建时间
- 新建快照（名称/描述）
- 详情查看、**版本 diff**（与上一版本对比）
- **回滚**（确认弹框）与删除（confirm 不可撤销）
- 后端：versions CRUD + rollback + diff

## 8. 与专业术语集的联动（重点）

| 联动点 | 说明 |
|--------|------|
| 类别名称来源 | 类别名可取自术语集某字段值，按值循环生成类别（name_source=term_base + name_term_base_id + name_term_field） |
| Query 术语集 | 类别可挂载多个术语集，配置分组字段/值字段/参与 Query/去重/条数上限，用于构造动态 Query |
| 字段选项 | 术语集字段下拉：api/db 用 columns，manual 用内置字段，显示名取 column_aliases |
| 脚本工具 | 后处理/校验脚本可通过 `kb_tools.get_term_records("术语集名称","字段名")` 读取术语集 |
| 加载器 | 后端 `TermBaseValueLoader` 按 term_base_id 分组加载 active 词条供规则/取值使用（已登记） |

## 9. 后端接口清单

### schema_templates.py（/kbs/{kb_id}/schema-templates）
- GET/POST 列表/新建；GET/PUT/DELETE /{template_id}
- POST /{template_id}/categories；PUT/DELETE /categories/{category_id}
- POST /categories/{category_id}/fields；PUT/DELETE /fields/{field_id}

### extraction_config.py（/kbs/{kb_id}/extraction-config）
- GET 配置总览；GET/PUT /global
- GET/POST /prompts；GET/PUT/DELETE /prompts/{prompt_id}；PUT /prompts/{prompt_id}/save
- GET /rules/registry；GET/PUT /rules
- GET /scripts/io；GET/POST /scripts；PUT/DELETE /scripts/{script_id}；POST /scripts/run
- GET/POST /rule-groups；GET /rule-groups/{group_id}；PUT /rule-groups/{group_id}/items；DELETE /rule-groups/{group_id}
- GET/PUT /validation；GET/PUT /bindings
- GET/POST /versions；POST /versions/{version_id}/rollback；GET /versions/{version_id}；GET /versions/{version_id}/diff；DELETE /versions/{version_id}

### kb_extraction.py（/kbs/{kb_id}/extraction）
- GET /documents（可抽取文档）；GET /schemas（当前生效 Schema）
- POST /stream（流式抽取）；POST /（任务式抽取）；GET /results/{document_id}；GET /history/{document_id}；GET /export

## 10. 关键设计点（对当前项目建设的启示）

1. **三层 Schema**（模板→类别→字段）是结构化抽取的核心模型，类别支持参数覆盖全局；
2. **术语集深度联动**：类别名称来源 + Query 术语集（分组/取值/去重/上限）是抽取配置与术语集的关键耦合，当前项目 loader 已按此预留；
3. **Prompt 与 Schema 绑定**：按类别拆分 user 提示词 + 字段/系统参数占位符 + 调试面板；
4. **低代码脚本**：post/validation 脚本即函数 + IO 注册 + 调试，工具化访问术语集/检索；
5. **版本治理**：配置快照/diff/回滚，支持变更审计与回退；
6. **全局-类别两级参数**：全局默认 + 类别覆盖（置信度/top_k/rerank/max_tokens）；
7. **旧配置兼容**：引擎名归一化与参数迁移（glmocr→BaseExtract 等）；
8. 权限与隔离：viewer 只读、editor+ 管理、KB 级 RLS。

## 11. 结论

原项目抽取配置是“全局参数 + Schema + Prompt + 规则 + 脚本 + 版本”六位一体的配置中心，
与专业术语集通过“类别名称来源 / Query 术语集 / 脚本工具 / 加载器”四条链路深度耦合。
当前项目后续建设抽取配置模块时，可据此确定页面结构、数据模型与术语集联动接口，
并沿用全局-类别两级参数与版本治理设计。
