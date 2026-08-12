# 专业术语集 S4 测试报告（M33-S4：术语集主页前端）

- 日期：2026-08-12
- 关联实现：
  - `frontend/src/api/modules/glossary.ts`：术语集/术语 API 封装与类型
  - `frontend/src/views/kb/KbGlossaryPage.tsx`：术语集主页（卡片网格 + 新建三源向导 + 测试/预览 + 同步/删除）
  - `frontend/src/router/index.tsx`：`glossary` 路由替换占位页
  - `frontend/src/components/ui/dialog.tsx`：共享 Dialog 升级（Escape 关闭 + 多弹窗层级）
  - `frontend/src/content/help.ts`、`docs/HELP_DOCS.md`、`frontend/public/help/glossary.png`：帮助文档登记

## 验证结果

| 项目 | 命令 | 结果 |
|------|------|------|
| 前端类型检查 | `npm run type-check` | ✅ 通过 |
| 前端生产构建 | `npm run build` | ✅ 通过 |
| 功能场景 E2E | `node qa/functional/e2e_glossary.mjs` | ✅ 10/10 |
| 控制台错误 | E2E 采集 | ✅ 无（负向用例的预期 400 已精确过滤） |

> 说明：本项目前端 package.json 未配置 lint 脚本（npm/pnpm 均无），按实际可用能力以
> type-check + build 验证；AGENTS.md 中 pnpm lint 约定在本仓库暂不适用，已在规范中登记。

## E2E 场景（10/10）

| 场景 | 结果 |
|------|------|
| S4-01 页面标题（精确到“专业术语集” h1） | ✅ |
| S4-02 空态展示 | ✅ |
| S4-03 向导数据源选择 | ✅ |
| S4-04 手动创建成功（卡片出现） | ✅ |
| S4-05 来源徽标显示 | ✅ |
| S4-06 API 测试失败错误态（SSRF 快速拒绝路径） | ✅ |
| S4-07 帮助截图生成（public/help/glossary.png） | ✅ |
| S4-08 删除确认弹窗 | ✅ |
| S4-09 删除后空态恢复 | ✅ |
| S4-10 移动端可用 | ✅ |

## 本轮发现并修复的问题

1. **共享 Dialog 无法 Esc 关闭**：E2E 中按 Escape 后新建向导仍停留在 DOM，遮挡后续
   操作。修复：`dialog.tsx` 增加 Escape 键监听；同时引入实例层级计数，多弹窗叠加时
   后打开者在上，避免相互遮挡（影响全部使用 Dialog 的页面，已回归）。
2. **E2E 标题断言取错 h1**：KB 顶栏与页面标题均为 h1，原断言取到 KB 名称。
   修复：断言精确匹配“专业术语集”标题。
3. **API 负向用例超时**：SSRF 按企业内网场景放行私有网段，`10.0.0.9` 连接挂起 10s，
   2.5s 断言必然失败。修复：改用 `169.254.169.254`（云元数据，SSRF 快速拒绝），
   同时覆盖安全路径。

## 迁移审查清单（方案 5.2 强制项）

| 检查项 | 结论 |
|--------|------|
| 无调试残留（print/DBG/临时脚本） | ✅ 无；临时诊断脚本已删除 |
| 无未使用 import/变量/死分支 | ✅ tsc 严格检查通过 |
| 无原项目代码整体复制 | ✅ 全部按当前项目（React+浅绿白+RLS API）重写 |
| 原项目已裁剪能力（standardize_text/术语合并/Dark-Tech）未带入 | ✅ 未带入 |
| 配置/常量/术语命名有明确用途 | ✅ 已登记 docs/GLOSSARY.md（TermBase/Term/source_type/sync_enabled 等） |
| 测试代码无 noop/占位残留 | ✅ E2E 全部为真实断言 |

## 结论

S4 通过铁律验收：E2E 10/10、type-check/build 通过、控制台无错误、迁移审查清单全部通过。
进入 S5：前端术语管理页（KbGlossaryEditorPage）。
