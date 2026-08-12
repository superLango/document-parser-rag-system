# 抽取配置四项复刻 · S4 报告（前端 Prompt 模板页 + 编辑器）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S4

## 交付

- `frontend/src/api/modules/extractionConfig.ts`：追加 promptApi（list/get/create/update/save/remove）与类型
- `frontend/src/views/kb/KbExtractionConfigPage.tsx`：Prompt 页签（列表/新建/编辑信息/删除/进入编辑页），
  支持 URL `?tab=` 页签同步
- `frontend/src/views/kb/KbPromptEditorPage.tsx`：独立 Prompt 编辑器路由
- `frontend/src/router/index.tsx`：`extraction-config/prompts/:promptId` 路由注册

## 页面功能

### Prompt 列表（抽取配置 Prompt 页签）
- 列表：名称、模式徽章（simple/schema）、绑定 Schema 模板名、启用状态
- 新建：名称/描述/模式（simple / schema 绑定模板 + 类别勾选，术语库类别带徽章）/启用
- 编辑信息、删除（确认弹框）、进入编辑页

### Prompt 编辑器（独立路由）
- simple：system + user 提示词编辑，保存全量写入
- schema：system 提示词 + 三栏（左类别列表 / 中当前类别 user 提示词 / 右字段与系统参数）
  - 字段点击插入 `${字段名}` 占位符；系统参数（feature/schema/context 等）插入 system
  - 术语集参数引用（类别名称来源/Query 术语集自动并入字段列表）
  - “渲染预览”：替换占位符展示（非 LLM 调用）
- 启用开关；保存后返回列表（定位到 Prompt 页签）

## 测试（M34-S4）

| 项目 | 结果 |
|------|------|
| 前端 type-check + build | ✅ |
| E2E（`qa/functional/e2e_extraction_prompt.mjs`） | ✅ 8/8 |
| 控制台错误 | ✅ 无 |

E2E 覆盖：页签与空态、新建 simple、simple 编辑器保存返回、新建 schema（绑定模板+勾选类别）、
schema 三栏字段占位符插入、渲染预览、删除确认、移动端。

## 迁移审查清单

| 检查项 | 结论 |
|--------|------|
| 无调试残留/未使用 import | ✅ type-check 通过 |
| 无原项目整体复制 | ✅ React+浅绿白重写 |
| 未迁移无用能力（LLM 试跑/TestPanel 真实调用） | ✅ 仅渲染预览 |
| 通用组件复用 | ✅ Tabs/Switch/Dialog 复用 |

## 结论

S4 通过铁律验收（E2E 8/8，build 通过）。下一步 S5：前端后处理与校验规则页。
