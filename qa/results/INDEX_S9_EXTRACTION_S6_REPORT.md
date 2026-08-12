# 抽取配置四项复刻 · S6 报告（前端脚本管理页）

- 日期：2026-08-12
- 依据：[EXTRACTION_CONFIG_REPLICATION_PLAN.md](../../docs/EXTRACTION_CONFIG_REPLICATION_PLAN.md) S6

## 交付

- `frontend/src/api/modules/extractionConfig.ts`：追加 scriptApi（io/list/create/update/remove/run）与类型
- `frontend/src/views/kb/KbScriptManager.tsx`：脚本管理组件（左中右 + 底部调试）
- `frontend/src/views/kb/KbExtractionConfigPage.tsx`：脚本页签接入组件

## 页面功能

- 左：目录（抽取后处理 post / 校验 validation）+ 脚本列表 + 新建
- 中：脚本编辑（名称/描述/启用/代码编辑器）+ 保存（脏标记）/删除（确认）
- 右：IO 注册折叠面板（输入参数/返回参数/可用工具）
- 底部：调试运行（args JSON → run → 结果/错误展示；运行按钮 loading）
- 权限：editor+ 可管理，viewer 只读

## 测试（M34-S6）

| 项目 | 结果 |
|------|------|
| 前端 type-check + build | ✅ |
| E2E（`qa/functional/e2e_extraction_scripts.mjs`） | ✅ 8/8 |
| 控制台错误 | ✅ 无 |

E2E 覆盖：脚本页签/目录/空态、post 与 validation 目录新建保存、调试运行成功（回显 records）、
脚本读取术语集（async run + kb_tools.get_term_records）、超时返回错误（非 500）、删除确认、移动端。

## 迁移审查清单

| 检查项 | 结论 |
|--------|------|
| 无调试残留/未使用 import | ✅ type-check 通过 |
| 无原项目整体复制 | ✅ React+浅绿白重写 |
| 脚本执行安全边界 | ✅ 受限子进程（-I/10s/1MB/术语集只读注入） |
| 未迁移无用能力（真实检索/嵌入工具、LLM 调用） | ✅ 工具为桩/术语集只读 |

## 结论

S6 通过铁律验收（E2E 8/8，build 通过）。四项前端（Schema/Prompt/规则/脚本）已全部完成，
下一步 S7：整体验收（四项联动真实链路 + M34 全量五层 + 覆盖率统计表 + 帮助文档）。
