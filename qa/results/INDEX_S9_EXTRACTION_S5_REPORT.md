# 抽取配置四项复刻 · S5 报告（前端后处理与校验规则页）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S5

## 交付

- `frontend/src/api/modules/extractionConfig.ts`：追加 ruleGroupApi（list/create/get/saveItems/remove）与类型
- `frontend/src/views/kb/KbExtractionConfigPage.tsx`：规则页签完整实现

## 页面功能

- 规则组列表：名称（默认取模板名）、绑定 Schema 模板、类别数、规则项数；新建/删除（确认弹框）
- 新建规则组：绑定 Schema 模板（一个模板至多一个规则组，后端 409 提示）、名称（留空用模板名）、描述
- 规则组详情：绑定模板下全部类别；每类别展示规则项（脚本名、启用状态）
- 规则项编辑弹窗：按类别全量替换；每条含脚本名、参数 JSON、启用开关；支持多条与移除；参数 JSON 校验
- 权限：editor+ 可管理，viewer 只读

## 测试（M34-S5）

| 项目 | 结果 |
|------|------|
| 前端 type-check + build | ✅ |
| E2E（`qa/functional/e2e_extraction_rules.mjs`） | ✅ 7/7 |
| 控制台错误/警告 | ✅ 无 |

E2E 覆盖：规则页签空态、新建规则组、详情类别展示、两类分别添加规则项并保存、删除确认与级联、移动端。

## 迁移审查清单

| 检查项 | 结论 |
|--------|------|
| 无调试残留/未使用 import | ✅ type-check 通过 |
| 无非法 DOM 嵌套 | ✅ 修复 button 嵌套（规则组列表项改 div role=button） |
| 无原项目整体复制 | ✅ React+浅绿白重写 |
| 未迁移无用能力（validation/bindings 独立表、全局配置） | ✅ 未实现 |

## 结论

S5 通过铁律验收（E2E 7/7，build 通过）。下一步 S6：前端脚本管理页。
