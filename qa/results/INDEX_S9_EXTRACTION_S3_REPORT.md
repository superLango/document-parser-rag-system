# 抽取配置四项复刻 · S3 报告（前端 Schema 模板页）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S3

## 交付

- `frontend/src/api/modules/extractionConfig.ts`：Schema 模板/类别/字段 API 封装与类型
- `frontend/src/components/ui/tabs.tsx`：通用 Tabs 组件（浅绿白）
- `frontend/src/components/ui/switch.tsx`：通用 Switch 组件（含属性透传）
- `frontend/src/views/kb/KbExtractionConfigPage.tsx`：抽取配置单页 4 页签 + Schema 完整实现
- `frontend/src/router/index.tsx`：抽取配置占位页替换

## 页面功能（Schema）

- 单页 4 页签：Schema 模板 / Prompt 模板 / 后处理与校验规则 / 脚本管理（后三者为后续阶段占位）
- 模板：列表（启用/停用徽标、类别数）、新建/编辑/删除（确认弹框、级联）
- 类别：名称来源手动/术语集（术语集+取值字段联动，manual 内置字段 / api-db columns+aliases）、
  返回类型、抽取策略、固定 Query、Query 术语集（多条目：显示名/术语集/分组字段/值字段/参与 Query/精简/主查询与精简上限）、
  类别级覆盖（置信度/top_k/rerank/max_tokens）、启用；展开区展示 Query 术语集徽标
- 字段：名称/类型/描述/示例/必填，CRUD
- 权限：editor+ 可见写操作，viewer 只读

## 测试（M34-S3）

| 项目 | 结果 |
|------|------|
| 前端 type-check + build | ✅ |
| E2E（`qa/functional/e2e_extraction_schema.mjs`） | ✅ 9/9 |
| 控制台错误 | ✅ 无 |

E2E 覆盖：菜单入口进入、4 页签、未开放占位、新建模板、手动类别、字段、术语集名称来源（使用术语库徽标）、
Query 术语集配置、删除确认与级联、移动端。

## 迁移审查清单

| 检查项 | 结论 |
|--------|------|
| 无调试残留/未使用 import | ✅ type-check 通过 |
| 无原项目整体复制 | ✅ React+浅绿白重写，组件复用/新增通用组件 |
| 未迁移无用能力 | ✅ 未实现 global/versions 等 |
| 通用组件避免页面重复实现 | ✅ Tabs/Switch 建在 components/ui |

## 结论

S3 通过铁律验收（E2E 9/9，build 通过）。下一步 S4：前端 Prompt 模板页 + 编辑器。
