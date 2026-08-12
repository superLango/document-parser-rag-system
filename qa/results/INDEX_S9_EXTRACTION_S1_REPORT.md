# 抽取配置四项复刻 · S1 报告（模型与迁移）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S1

## 交付

- `backend/alembic/versions/012_extraction_config.py`：8 张 KB 域表 + 索引 + RLS（ENABLE/FORCE，32 条策略）
- `backend/app/models/extraction.py`：SchemaTemplate / SchemaCategory / SchemaField / PromptTemplate /
  PromptContent / RuleGroup / RuleGroupItem / KbScript
- `backend/app/models/__init__.py`：模型注册
- 迁移已应用：开发库 `hanson_doc_rag` 与测试库 `hanson_doc_rag_test`

## 表结构与关键约束

| 表 | 关键约束 |
|----|----------|
| schema_templates | unique(kb_id, name) |
| schema_categories | FK template CASCADE；name_term_base_id → term_bases SET NULL；query_sources JSONB |
| schema_fields | unique(category_id, name)；FK category CASCADE |
| prompt_templates | unique(kb_id, name)；schema_template_id SET NULL；category_ids JSONB |
| prompt_content | unique(prompt_id, category_id)；partial unique(prompt_id) WHERE category_id IS NULL |
| rule_groups | unique(kb_id, name) |
| rule_group_items | FK group CASCADE；category_id SET NULL；params JSONB |
| kb_scripts | unique(kb_id, folder, name) |

全部表：kb_id + RLS（SELECT=成员，写=owner/admin/editor）、删除硬删（FK CASCADE）。

## 测试（M34-S1）

| 分层 | 文件 | 用例 | 结果 |
|------|------|------|------|
| L1 单元 | `qa/unit/test_extraction_models.py` | 6 | 通过 |
| L2 集成 | `qa/integration/test_extraction_storage.py` | 2 | 通过 |
| L4 边界 | `qa/boundary/test_extraction_storage_boundary.py` | 4 | 通过 |
| L5 安全 | `qa/security/test_extraction_storage_security.py` | 4 | 通过 |
| **小计** | | **16** | **16 通过** |

覆盖点：迁移产物（8 表/32 策略/唯一索引）、ORM 写入读取、模板→类别→字段级联删除、
规则组→规则项级联、Prompt→内容级联、模板/字段/脚本重名唯一、simple Prompt 单内容唯一、
RLS 无上下文拒绝/viewer 只读/editor 可写/跨 KB 隔离。

## 迁移审查清单（方案强制项）

| 检查项 | 结论 |
|--------|------|
| 无调试残留/临时脚本 | ✅ |
| 无未使用 import/死分支 | ✅ ruff 通过 |
| 无原项目整体复制 | ✅ 按当前项目模型风格重写 |
| 未迁移无用能力（regex/field_templates/bindings/旧引擎兼容） | ✅ 未建表 |
| 常量/术语登记 | ✅ 常量定义在 models/extraction.py，方案已登记 |
| 测试无 noop 占位 | ✅ 全部真实断言 |

## 结论

S1 通过铁律验收（16/16，ruff 通过，两库迁移一致）。下一步 S2：后端 API。
