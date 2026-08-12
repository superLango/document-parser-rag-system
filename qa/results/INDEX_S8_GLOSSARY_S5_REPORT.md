# 专业术语集 S5 测试报告（M33-S5：前端术语管理页）

- 日期：2026-08-12
- 关联实现：
  - `frontend/src/views/kb/KbGlossaryEditorPage.tsx`：术语管理页（筛选/表格/移动卡片/新增编辑/批量导入/审核/导出/删除）
  - `frontend/src/api/modules/glossary.ts`：补充 createTerm/updateTerm/reviewTerm/deleteTerm/batchImport/exportTerms
  - `frontend/src/router/index.tsx`：`glossary/:baseId` 路由替换占位页
  - `frontend/src/content/help.ts`、`docs/HELP_DOCS.md`、`frontend/public/help/glossary-editor.png`：帮助文档登记
  - `docs/GLOSSARY.md`：补充“术语条目（term）”业务术语

## 验证结果

| 项目 | 命令 | 结果 |
|------|------|------|
| 前端类型检查 | `npm run type-check` | ✅ 通过 |
| 前端生产构建 | `npm run build` | ✅ 通过 |
| 功能场景 E2E | `node qa/functional/e2e_glossary_editor.mjs` | ✅ 16/16 |
| 控制台错误 | E2E 采集 | ✅ 无 |
| 后端全量回归（S1-S3） | `pytest`（术语模块 14 个文件） | ✅ 62/62 |

> 说明：S5 为纯前端阶段，五层测试中后端 L1-L5 以 62/62 回归覆盖；
> 前端验证采用 type-check + build + 功能/边界/权限/移动端 E2E。
> 本项目前端 package.json 未配置 lint 脚本，验证方式已在 S4 报告登记。

## E2E 场景（16/16）

| 场景 | 结果 |
|------|------|
| S5-01 页面标题与返回链接 | ✅ |
| S5-02 空态与操作按钮（新建/批量导入/导出） | ✅ |
| S5-03 新建术语成功（含已通过徽标） | ✅ |
| S5-04 编辑术语更新分类 | ✅ |
| S5-05 审核驳回/通过状态流转 | ✅ |
| S5-06 状态筛选-待审核空态 | ✅ |
| S5-07 状态筛选-已通过命中 | ✅ |
| S5-08 分类筛选命中 | ✅ |
| S5-09 关键词筛选无命中空态 | ✅ |
| S5-10 CSV 批量导入（预览+导入） | ✅ |
| S5-11 JSON 批量导入 | ✅ |
| S5-12 导出 CSV（含表头与导入词条） | ✅ |
| S5-13 帮助截图生成（glossary-editor.png） | ✅ |
| S5-14 查看者只读（无写操作按钮，可导出） | ✅ |
| S5-15 删除术语（确认弹窗+行消失） | ✅ |
| S5-16 移动端卡片展示 | ✅ |

## 关键覆盖点

1. 术语 CRUD：新建/编辑/删除均带确认与错误 toast；删除为软删除；
2. 审核流：驳回→已驳回、通过→已通过，状态徽标随列表刷新；
3. 批量导入：CSV（含引号解析）与 JSON 两种格式，预览前 10 条，≤5000 条前端拦截，
   同术语集按名称幂等 upsert（后端 S3 已测）；
4. 导出：真实触发浏览器下载，校验 UTF-8 BOM 表头与导入词条；
5. 权限：viewer 只读（新建/批量导入/编辑/审核/删除均不可见，导出可见）；
6. 移动端：卡片式列表，操作按钮保留，表格在 md 以下隐藏。

## 本轮发现并修复的问题

1. **E2E 正则转义错误**：脚本中 SSRF 过滤正则多一层反斜杠，修正后恢复执行；
2. **E2E 数据同步时序**：API 创建词条后页面未自动刷新，先 reload 再操作审核/删除，
   与真实使用（页面内操作触发 invalidate）一致。

## 迁移审查清单（方案 5.2 强制项）

| 检查项 | 结论 |
|--------|------|
| 无调试残留（print/DBG/临时脚本） | ✅ 无 |
| 无未使用 import/变量/死分支 | ✅ tsc 严格检查通过 |
| 无原项目代码整体复制 | ✅ 全部按当前项目（React+浅绿白+React Query+统一组件库）重写 |
| 原项目已裁剪能力未带入（standardize_text/术语合并等） | ✅ 未带入 |
| 前端构建产物无类型错误 | ✅ build 通过 |
| 业务术语/常量登记 | ✅ GLOSSARY.md 已补充术语条目 |

## 结论

S5 通过铁律验收：E2E 16/16、后端 62/62 回归、type-check/build 通过、控制台无错误。
进入 S6：整体验收（真实链路 + M33 全量五层 + 覆盖率统计表归档）。
