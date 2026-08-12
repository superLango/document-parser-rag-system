# 抽取配置四项复刻 · S2 报告（后端 API）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S2

## 交付

- `app/schemas/extraction.py`：Schema 模板/类别/字段、Prompt 创建/更新/保存、规则组、脚本 schema（枚举校验）
- `app/services/extraction_config_service.py`：四模块业务逻辑 + 受限脚本执行
- `app/api/v1/endpoints/kb_extraction_config.py`：`/kb/{kb_id}/schema-templates` 与 `/kb/{kb_id}/extraction-config` 两组端点
- `app/api/v1/router.py`：路由注册
- `alembic/versions/013_extraction_rulegroup_fix.py`：rule_groups 补 schema_template_id/description（对齐原项目规则组绑定模板），两库已应用

## 端点清单

### Schema 模板（/kb/{kb_id}/schema-templates）
- 模板：GET/POST 列表/新建；GET/PUT/DELETE /{template_id}
- 类别：POST /{template_id}/categories；PUT/DELETE /categories/{category_id}
- 字段：POST /categories/{category_id}/fields；PUT/DELETE /fields/{field_id}
- 校验：模板/字段重名 409；类别枚举（return_type/extraction_strategy/name_source）、字段 type、术语集引用归属

### 抽取配置（/kb/{kb_id}/extraction-config）
- Prompt：GET/POST /prompts；GET/PUT/DELETE /prompts/{id}；PUT /prompts/{id}/save（simple 全量、schema 按类别 upsert，非法类别 400）
- 规则组：GET/POST /rule-groups（一模板一规则组 409）；GET /rule-groups/{id}（类别+规则项）；PUT /rule-groups/{id}/items（按类别全量替换）；DELETE
- 脚本：GET /scripts/io；GET/POST /scripts；PUT/DELETE /scripts/{id}；POST /scripts/run（受限子进程）
- 脚本运行：`-I` 隔离、10s 超时、1MB 输出上限、注入当前 KB 术语集只读数据（get_term_records 可用）、`asyncio.to_thread` 非阻塞

## 测试（M34-S2）

| 分层 | 文件 | 用例 | 结果 |
|------|------|------|------|
| L1 单元 | `qa/unit/test_extraction_s2_unit.py` | 4 | 通过 |
| L2/L3 集成 | `qa/integration/test_extraction_s2_api.py` | 4 | 通过 |
| L4 边界 | `qa/boundary/test_extraction_s2_boundary.py` | 7 | 通过 |
| L5 安全 | `qa/security/test_extraction_s2_security.py` | 4 | 通过 |
| **S2 小计** | | **19** | **19 通过** |

M34 全量（S1+S2）：**35/35**；ruff 全部通过。

覆盖点：Schema 三层全流程、术语集名称来源/Query 术语集引用、Prompt simple/schema 保存与非法类别、规则组绑定模板与规则项全量替换、脚本 CRUD/IO/受限运行/术语集注入/超时、重名/枚举/引用归属边界、viewer 只读/editor 写/非成员 403/跨 KB 隔离/脚本运行权限。

## 迁移审查清单

| 检查项 | 结论 |
|--------|------|
| 无调试残留/临时脚本 | ✅ |
| 无未使用 import/死分支 | ✅ ruff 通过 |
| 无原项目整体复制 | ✅ 按当前项目分层/校验/审计规范重写 |
| 未迁移无用能力（global/versions/validation/bindings/regex/旧引擎兼容） | ✅ 未实现 |
| 脚本执行安全边界 | ✅ 子进程隔离 + 超时 + 输出上限 + 只读术语集注入 |
| 测试无 noop 占位 | ✅ 全部真实断言 |

## 结论

S2 通过铁律验收（19/19，M34 合计 35/35）。下一步 S3：前端 Schema 模板页。
