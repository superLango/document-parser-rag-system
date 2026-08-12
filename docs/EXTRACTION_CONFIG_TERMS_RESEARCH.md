# 抽取配置与专业术语集调研（原项目实现，2026-08-12）

> 范围：`document-parser-rag-system` 中「抽取配置」与「专业术语集」两个模块。
> 说明：原项目 `backend/app/models/` 因 `.gitignore models/` 历史问题**未入库**
> （ORM 模型文件缺失），本文档基于 API、Schema、服务层代码推导数据结构，并标注依据文件。

## 一、抽取配置（Extraction Config Center）

### 1.1 定位与分层

KB 隔离的「抽取配置中心」，管理结构化抽取全部可配置项，运行时由
`ExtractionConfigResolver` 聚合为单一 `ExtractionDomainConfig` 供流水线消费
（`app/services/extraction_config/resolver.py`）。

配置分层（resolver 文档注释）：
- **全局层**：`kb_extraction_config`（retrieval / llm / post_process 三节）
- **模板层**：`kb_prompt_templates` + `kb_term_bindings`
- **Schema 层**：`schema_templates` + `schema_configs`（类别/字段三层）

解析策略：**仅读用户显式配置，缺失即运行时报错**（不做内置默认回退），
提交前由 `config_validator` 全量校验。

### 1.2 数据实体（从 API/服务推导）

| 实体 | 用途 | 关键字段（推导） |
|------|------|------------------|
| KbExtractionConfig | 全局配置 | kb_id, enabled, content(JSON), version |
| KbPromptTemplate | Prompt 模板 | name, scope(simple/schema), system_prompt, user_prompt, schema_template_id, category_ids, is_active |
| KbPromptCategory | schema 模式按类别 user_prompt | category_id, user_prompt |
| KbRule | 后处理/校验规则 | rule_key, stage(post/validation), enabled, params, scope, sort_order |
| KbScript | 自定义脚本 | folder, name, code, params_schema, enabled |
| KbTermBinding | 术语绑定 | schema_id, field_name, term_base_id, config |
| KbDomainConfigVersion | 版本快照 | name, description, snapshot |
| SchemaTemplate / SchemaConfig | Schema 模板/实例 | name, schema_definition(JSON Schema), categories(含类别节点), is_template |

### 1.3 API（`/kbs/{kb_id}/extraction-config`）

- GET /（完整解析配置，含 global/prompt_templates/rules/validation_rules/term_bindings/schema_templates）
- GET|PUT /global；GET|POST /prompts，PUT|DELETE /prompts/{id}
- GET|PUT /rules（批量）；GET|PUT /validation（批量）
- GET|PUT /bindings（批量）；scripts CRUD + 调试运行
- /versions：列表 / 创建 / 详情 / diff / rollback / 删除
- 权限：读=有效成员，写=editor+（require_role(*EDIT_ROLES)）

### 1.4 运行时消费链

```
ExtractionConfigResolver.resolve(kb_id)
  → ExtractionDomainConfig
    ├─ category_builder（Schema 模板 → ExtractionTarget 列表）
    ├─ config_prompt_renderer（${feature}/${context}/${field_defs}... 渲染 Prompt）
    ├─ output_schema_builder（LangExtract XGrammar 输出约束 JSON Schema）
    ├─ rule_engine（RULE_REGISTRY 内置规则 + KbScript 自定义脚本 + Hook）
    └─ extraction_pipeline（Phase2 类别构建 → Phase3 检索 → Phase4 LLM 抽取+后处理）
```

### 1.5 领域模板与 KB 三层覆盖

- `app/domain_templates/`：general_qa / material_testing / medical_device，
  纯数据（CategoryDef/FieldTemplateDef/RegexRuleDef/enums/config_override/hook_template）
- `domain_template_service.init_kb_from_template`：模板 → kb_categories/kb_field_templates/kb_regex_rules + Hook 脚本
- `kb_config_loader`：全局 settings 默认 → KB config JSON → 领域配置表 三层覆盖

## 二、专业术语集（Term Base）

### 2.1 定位

术语标准化库 + 抽取联动（类别名称展开、字段取值、Query 检索词组、后处理取值）。

### 2.2 数据实体（从 API/Schema/服务推导）

| 实体 | 用途 | 关键字段 |
|------|------|----------|
| TermBase | 术语库 | name, source_type(manual/api/db), column_aliases, extras |
| Term | 术语条目 | term_name, standard_name, definition, synonyms, category, status(active/...), extras |
| KbTermBinding | 术语绑定（抽取配置侧） | schema_id, field_name, term_base_id, config |

### 2.3 API

- **kb_term_bases**：TermBase CRUD；test-api / test-db / db-tables / preview-sql（外部源连通性测试与预览）；/{base_id}/terms 列表；/{base_id}/terms/batch 批量保存；/{base_id}/sync 从源同步
- **kb_terms**：列表 / 详情 / 创建 / 批量导入 / 更新 / review 审核 / 删除 / export 导出 / categories 类别列表

### 2.4 在抽取中的联动（核心）

`category_builder`（app/services/extraction/category/category_builder.py）：

1. **名称展开**：类别 `name_source=term_base` 时按术语集字段值循环生成多个类别实例
   （`_expand_names`，如牌号列表逐项成为抽取目标）
2. **字段取值**：`_enrich_fields` 从术语绑定（term/dataset）解析可选值，注入 Schema 与白名单
3. **Query 词组**：`fixed_query` + `query_sources`（Query 术语集）组装检索词
   （`_load_query_source_terms`），支持 `group_field` 分组（按类别实例取对应分组词条）
4. **后处理/校验取值**：`TermBaseValueLoader`（term_base_loader.py）按需加载术语集字段值
   并缓存（value_field 按 column_aliases 新表头匹配，回退原始字段/内置字段），
   结果组织为 `{group_value: {field: [value...]}}`，无分组时固定 `__ALL__`

### 2.5 三种数据来源

- **manual 手动**：内置字段（term_name/standard_name/definition/category/synonyms/aliases/standard_number），按 category 分组
- **api**：外部 API 源（测试连接 → 同步）
- **db**：数据库源（测试连接 → 表列表 → SQL 预览 → 同步），extras.group/分组 作为分组键

## 三、迁移到新项目的要点（对照）

### 需要新建的 KB 域表（全部 kb_id + RLS）

```
kb_extraction_config / kb_prompt_templates / kb_prompt_categories
kb_rules / kb_scripts / kb_term_bindings / kb_domain_config_versions
schema_templates / schema_configs
term_bases / terms
kb_categories / kb_category_enums / kb_field_templates / kb_regex_rules
```

### 与新项目已有设施的衔接

- **检索**：原项目 Phase2/3 用五维向量 hybrid_search；新项目已有双向量+BM25+RRF
  `retrieval_service`，抽取类别检索可直接复用（query 编码改为 title/content 双路 + filters）
- **LLM**：原项目 llm_extract（glmocr/langextract 双线路 + XGrammar 输出约束）；
  新项目 LLM 兼容层未建，vllm Qwen（9988）已就绪，可借鉴 lightRAG 角色化 LLMClient
- **规则/脚本**：RULE_REGISTRY + KbScript + Hook 是执行逻辑，可整体迁移（纯 Python）
- **配置校验**：config_validator + snapshot_io（版本快照/对比/回滚）可直接复用

### 待确认点

1. 新项目是否保留「领域模板」（创建 KB 时选模板）？此前已确认**知识库创建不选领域模板**，
   但模板可作为「抽取配置」的导入/初始化来源保留
2. 术语集三种来源（manual/api/db）是否全保留，还是先做 manual？
3. 版本快照/回滚是否本期实现？
4. Hook 脚本（kb_hooks/{kb_id}/hooks.py）迁移方式（文件 vs DB 存储）
