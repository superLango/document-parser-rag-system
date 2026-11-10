# 前端功能取舍与改造清单

> 阶段：M1.9a（前端范围确认）
> 状态：draft v0.1（待业务确认）
> 日期：2026-10-27
> 约束：188.75 上的 hansonDoc_RAG 原项目**只读参考，不做任何修改**；所有新代码在当前项目 `f:\hanson\hanson_doc_parse` 下。

---

## 1. 结论

- 前端**不整体照搬**，按业务取舍：保留可用页面、改造核心页面、新建标准拆分页面、删除无关模块。
- **知识库/成员/工作空间/群组/邀请不简化**，后续继续完善；保留 API Key 外部对接能力。
- **完整术语集功能不保留**：不做 api/db 三源编辑器、批量编辑、审核 UI；只保留“业务词典/别名管理”，允许人工别名与 pending 确认。
- 复核单角色即可，不做多人/多角色流转。
- 前端先定稿，后端按前端最终功能完善；**前端驱动后端**。

---

## 2. 取舍原则

1. 标准拆分主链路优先：上传 → 解析 → 项目清单 → 记录/条款/证据 → 复核。
2. 与标准拆分无关的 RAG/图谱/向量搜索不建。
3. 旧抽取配置（Schema/类别/Prompt/脚本）不保留，改由配方/覆盖模板配置文件驱动。
4. 可复用页面/组件先审计再迁移；不迁移的页面/路由/菜单/依赖彻底删除。
5. 业务系统已有项目/方法主数据，前端只做展示、确认、别名维护，不做主数据源。

---

## 3. 模块取舍矩阵

| 模块/页面 | 当前文件/路由 | 取舍 | 理由 | 优先级 | 后端影响 |
|---|---|---|---|---|---|
| 登录 | `views/LoginPage.tsx` `/login` | **保留** | 内部使用 | P0 | 认证接口迁移+审计 |
| 工作台 | `views/DashboardPage.tsx` `/` | **保留/简化** | 可做任务概览 | P1 | 统计接口简化 |
| 个人中心 | `views/ProfilePage.tsx` `/profile` | **保留** | 账号基础 | P2 | 用户接口 |
| 帮助/关于 | `HelpPage.tsx` `AboutPage.tsx` | **保留/后置** | 不影响主链路 | P2 | 无 |
| 知识库列表/创建 | `KnowledgeBasesPage.tsx` `/kb` | **保留/完善** | 业务确认不简化，后续继续完善 | P0 | 知识库/成员接口保留 |
| 知识库概览 | `KbOverviewPage.tsx` `/kb/:id` | **保留/完善** | 不简化，增加拆分统计 | P1 | 统计接口 |
| 文档列表/上传/进度 | `KbDocumentsPage.tsx` `/kb/:id/documents` | **保留/改造** | 核心入口；增加标准拆分任务类型 | P0 | 文档/任务接口 |
| 文档内页 | `KbDocumentViewerPage.tsx` `/kb/:id/documents/:docId/viewer` | **改造** | 增加项目/记录/条款/证据标签 | P0 | 结果/证据接口 |
| 任务列表 | `KbTasksPage.tsx` `/kb/:id/tasks` | **保留/改造** | 显示解析/引擎状态、缺口、重试 | P0 | 任务接口 |
| 标准拆分列表 | `KbStructuredExtractionPage.tsx` `/kb/:id/extraction` | **改造** | 改为标准拆分入口 | P0 | 引擎任务 |
| 拆分结果详情 | `KbExtractionDetailPage.tsx` `/kb/:id/extraction/:docId` | **改造** | 改为项目/记录/条款/证据视图 | P0 | 结果接口 |
| 独立结果页 | `KbExtractionStandaloneLayout.tsx` `/extraction/:kbId/:docId` | **保留/改造** | 免登录/对接结果页可复用 | P1 | 会话令牌/结果接口 |
| 业务词典 | `KbGlossaryPage.tsx` `/kb/:id/business-dictionary` | **改造** | 改为业务词典/别名管理；允许人工别名与 pending | P1 | 词典同步/确认 |
| 术语集编辑器 | `KbGlossaryEditorPage.tsx` `/kb/:id/glossary/:baseId` | **删除（并入业务词典）** | 不做 api/db 三源、批量编辑、审核 UI；别名/pending 并入业务词典 | P2 | 移除对应接口 |
| 抽取配置 | `KbExtractionConfigPage.tsx` `/kb/:id/extraction-config` | **删除** | 配方/覆盖模板用配置 | — | 移除 API/表 |
| Prompt 编辑器 | `KbPromptEditorPage.tsx` | **删除** | 不再按类别配置 Prompt | — | 移除 API |
| 规则组/脚本 | `KbRuleGroups.tsx` `KbScriptManager.tsx` | **删除** | 不跑用户脚本 | — | 移除 API/执行器 |
| 全局配置 | `KbGlobalConfig.tsx` | **删除/只读** | 模型固定，不需要在线配置 | — | 移除/只读 |
| 向量搜索 | `KbVectorSearchPage.tsx` `/kb/:id/vector-search` | **删除** | 本期不做 RAG | — | 移除检索依赖 |
| 知识图谱 | `KbPlaceholderPage` `/kb/:id/graph` | **删除** | 不属于标准拆分 | — | 移除路由/菜单 |
| 知识问答 | `KbPlaceholderPage` `/kb/:id/qa` | **删除** | 不属于标准拆分 | — | 移除路由/菜单 |
| 知识库成员 | `KbMembersPage.tsx` | **保留** | 知识库权限需要 | P1 | 成员接口保留 |
| 资源与配置 | `KbResourcesPage.tsx` | **保留/完善** | 不简化，保留资源与模型配置 | P2 | 资源接口保留 |
| 工作空间/群组 | `WorkspacesPage.tsx` | **保留/完善** | 业务确认不简化，后续完善 | P2 | 保留接口/表 |
| API Key | `ApiKeysPage.tsx` | **保留** | 外部对接需要 | P1 | 保留 API Key |
| 邀请 | `InvitationsPage.tsx` | **保留** | 知识库成员邀请需要 | P2 | 保留接口 |
| 用户/角色/审计 | `admin/UsersPage.tsx` `RolesPage.tsx` `AuditLogsPage.tsx` | **保留/完善** | 权限与审计需要 | P1 | RBAC/审计保留 |

---

## 4. 新建页面

| 页面 | 路由建议 | 内容 | 依赖 |
|---|---|---|---|
| 项目清单 | `/kb/:id/documents/:docId/items` | 项目、family、facets、status、证据、筛选 | ItemInventory API |
| 记录 | `/kb/:id/documents/:docId/records` | 牌号×条件×属性，值可点击 | Result API |
| 条款 | `/kb/:id/documents/:docId/clauses` | 方法/方向/位置/数量/温度/判定 | Clause API |
| 证据 | 右侧抽屉/标签 | 页码、表、行、列、quote、高亮 | Evidence API |
| 新项目/新方法 | `/kb/:id/documents/:docId/new-terms` | 确认、改名、映射、拒绝 | new-terms API |
| 业务词典 | `/kb/:id/business-dictionary` | 同步、别名、pending 确认 | Dictionary API |

---

## 5. 删除清单（必须彻底）

- 页面/路由：`/vector-search`、`/graph`、`/qa`、`/extraction-config`、`/extraction-config/prompts/:id`、`/glossary`、`/glossary/:baseId`（由 `/business-dictionary` 替代）。
- 组件/页面文件：`KbVectorSearchPage.tsx`、`KbExtractionConfigPage.tsx`、`KbPromptEditorPage.tsx`、`KbRuleGroups.tsx`、`KbScriptManager.tsx`、`KbGlobalConfig.tsx`（按最终决策）。
- API 模块：`extractionConfig.ts`、`indexing.ts`（若不做检索）、`glossary.ts` 中 api/db 三源/审核部分。
- 菜单入口：知识图谱、知识问答、向量搜索、抽取配置、旧术语集。
- 依赖：向量/检索相关依赖（若前端未使用）。

删除验收：构建通过、无路由/菜单/API 引用残留、E2E 主链路通过。

---

## 6. 已确认决策（2026-10-27）

1. **知识库不简化**：保留知识库/成员/工作空间/群组/邀请，后续继续完善功能。
2. **需要 API Key/外部对接**：保留 API Key 页面与接口能力。
3. **允许业务词典人工别名与 pending 条目**：保留别名维护与 pending→active 确认。
4. **复核单角色即可**：不做多人/多角色流转，保留单角色确认与审计。

---

## 7. 后端影响（供 M1.9 使用）

- 需要重写/完善：文档上传/任务、项目清单、记录/条款/证据、业务词典、复核、引擎 API。
- 需要迁移+审计：认证/RBAC/知识库/工作空间、文档/任务/Outbox、存储、parsekit、API Key。
- 需要删除：旧抽取配置、规则脚本、向量检索、RAG/图谱接口、旧术语集三源编辑。
- 知识库/工作空间/群组不简化，RBAC/RLS 保留并审计，不做项目级裁剪。
- 前端最终页面清单是后端 API 契约的输入。

---

## 8. 验收

- [ ] 保留/改造/新建/删除清单经业务确认；
- [ ] 删除项在构建中无残留；
- [ ] 主链路页面可操作：上传→解析→项目→记录→证据→复核；
- [ ] 知识库/成员/工作空间/API Key 保留可用；
- [ ] 业务词典允许人工别名与 pending；
- [ ] 复核单角色流程可用；
- [ ] 后端 API 草案覆盖所有保留/新建页面。
