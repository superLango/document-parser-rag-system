# 术语集创建导入与卡片入口缺陷修复报告（S8 缺陷修复）

- 日期：2026-08-12
- 现象：
  1. 接口源测试连接成功拿到数据，但点击“创建术语集”后词条没有插入；
  2. 点击术语集卡片无法进入术语管理页。

## 根因

1. **创建未携带预览数据**：前端 `submitCreate` 只提交了 `source_config`，
   没有把“测试连接/预览”得到的 rows 作为 `import_data` 传给后端，也没有置
   `auto_import`；后端 `create_term_base` 仅在 `auto_import=True` 时执行导入，
   因此创建出的术语集词条数为 0。
2. **卡片缺少入口**：`KbGlossaryPage` 的卡片只有“同步/删除”按钮，没有
   点击进入 `/kb/{kbId}/glossary/{baseId}` 的交互，卡片不可点。

## 验证盲区说明（用户问“你的验证是如何验证的”）

- 原 S4 E2E 只覆盖“API 测试连接失败态”（SSRF 拒绝），没有真实成功源，
  因此未覆盖“测试成功 → 创建 → 数据插入”链路；
- 原 S5 E2E 是**直接输入 URL** 进入术语管理页，没有验证卡片入口，
  所以“点击卡片进不去”未被发现。
- 本轮已补上真实链路验证：E2E 内置本地 HTTP 术语源（监听 192.168.188.75，
  内网地址，SSRF 放行），完整走通“测试连接成功 → 创建 → 自动导入 2 条 →
  点击卡片进入管理页 → 词条可见”的闭环。

## 修复内容

| 文件 | 修改 |
|------|------|
| `frontend/src/lib/glossaryImport.ts`（新增） | 共享导入归一化：外部行 → `term_name/standard_name/english_term/category/synonyms/aliases`，主页与编辑器复用，避免重复建设 |
| `frontend/src/views/kb/KbGlossaryPage.tsx` | 创建 API/DB 术语集时携带 `auto_import=true + import_data=预览数据`；创建成功提示“导入 N 条”；卡片可点击进入管理页（含“管理”按钮），同步/删除按钮阻止冒泡 |
| `frontend/src/views/kb/KbGlossaryEditorPage.tsx` | 删除本地重复归一化实现，改用共享模块 |
| `frontend/src/content/help.ts` | 帮助步骤补充“创建即导入预览数据”“点击卡片进入管理页” |

## 验证

| 项目 | 结果 |
|------|------|
| S4 E2E（新增 S4-11 接口源创建并自动导入、S4-12 卡片进入管理页） | ✅ 12/12 |
| S5 E2E（共享模块重构回归） | ✅ 16/16 |
| 前端 type-check + build | ✅ 通过 |
| 控制台错误 | ✅ 无 |

## 结论

两个缺陷均已修复并有真实链路 E2E 兜底。后续任何涉及“外部源创建/导入/入口”
的改动，S4 E2E 会直接拦截回归。
