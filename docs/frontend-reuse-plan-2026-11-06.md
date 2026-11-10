# 前端复用改造开发计划（hansonDoc_RAG → hanson_doc_parse）

> 日期：2026-11-06  
> 目标：以 hansonDoc_RAG 原前端为基线，保留其设计系统与交互，裁剪无用模块，补齐当前产品能力，适配当前平台 API；不再维护现有自研前端页面。  
> 原则：后端抽取链路不动；前端以“移植 + 适配器 + 小补口”为主，避免重新设计。

## 1. 结论与总体策略

1. **替换式迁移**：当前 `apps/web` 的 18 个页面逐步由 hansonDoc_RAG 前端替换，最终删除旧页面与旧组件，不做两套 UI 长期并存。
2. **保留原设计系统**：`AppShell`、浅绿主题 token、`components/ui/*`、`PageHeader`、`StatCard`、字体与动效全部复用，保证视觉与交互和原项目一致。
3. **API 适配层隔离差异**：原前端按 `/api/v1` + `{code,data}` 封装、refresh token、RBAC 权限码设计；当前后端是 `/v1` + 裸 JSON、单 access token、admin/user + 工作空间/知识库角色。新增 `api/adapters` 做 DTO 映射，尽量少改页面代码。
4. **只补必要后端接口**：文档列表字段、成员数、结果版本、结果元数据、工作台概览；不引入新的抽取/配置体系。
5. **安全审计前置**：原项目存在过 integration 无鉴权、结果页无鉴权等历史问题；本次不迁移这些路由，所有页面统一走当前 JWT + 知识库/工作空间成员校验。

## 2. 原前端基线盘点

原项目 `grainuser@192.168.188.75:~/hansonDoc_RAG/frontend`：

- 技术栈：React 19、Vite 5、TypeScript、Tailwind 4、React Router 6、TanStack Query、Zustand、Axios、lucide-react、Recharts。
- 目录：`layouts/AppShell.tsx`、`components/ui/*`（14 个基础组件）、`views/*`、`views/kb/*`、`views/admin/*`、`api/modules/*`、`stores/auth.ts`、`stores/rbac.ts`。
- 页面规模约 11,090 行；核心页面：
  - 登录、工作台、知识库列表、知识库详情（概览/文档解析/结构化抽取/任务/成员）
  - 结构化抽取列表、抽取详情（左 PDF、右 Schema 结果、可编辑表格、历史、缺失字段）
  - 文档查看器、工作空间、API Key、个人中心、用户管理、审计日志
  - 无用模块：向量搜索、知识问答、知识图谱、抽取配置（Schema/Prompt/规则组/脚本）、专业术语集编辑器、角色权限矩阵、待审批、集成任务结果页、资源与配置。

当前后端已具备：

- 认证/用户/工作空间/知识库/成员/邀请
- 文档上传/解析/重解析/删除/预览
- 结果 Schema（标准信息 + 项目信息 + 热处理信息）、记录/条款/证据/新词/字段复核
- 结果导出（hanson JSON/JSON/CSV/XLSX）、分享链接
- 业务词典、API Key、审计日志

## 3. 功能取舍清单

| 原模块 | 处置 | 目标页面/说明 |
| --- | --- | --- |
| `AppShell` / 登录 / 个人中心 / 403 / 404 | 保留 | 替换当前自研壳层与登录页；文案改为“金属标准拆分工作台” |
| `DashboardPage` | 改造 | 去掉 RAG 问答/图谱统计，改为知识库、文档、解析任务、待复核、最近任务 |
| `KnowledgeBasesPage` | 保留 + 适配 | 创建/删除/搜索知识库；成员邀请改为当前知识库成员接口 |
| `KbDetailLayout` | 改造 | 导航裁剪为：概览、文档解析、结构化抽取、任务、成员 |
| `KbOverviewPage` | 改造 | 当前知识库文档数、任务状态、最近结果；去掉 RAG 指标 |
| `KbDocumentsPage` | 保留 + 适配 | 上传 PDF、开始解析、重新解析、删除、查看原文；状态映射当前 `queued/running/succeeded/review/failed` |
| `KbStructuredExtractionPage` | 保留 + 适配 | 文档列表 + 历史；入口改为当前文档/任务结果 |
| `KbExtractionDetailPage` | **核心改造** | 左 PDF、右 Schema 结果；单模板、结果/复核/新词/证据/历史/导出/分享 |
| `KbDocumentViewerPage` | 保留 + 适配 | 接当前预览/页面图片/证据定位接口 |
| `KbTasksPage` | 保留 + 适配 | 当前 `/v1/tasks` 任务列表、状态、重试 |
| `KbMembersPage` | 保留 + 适配 | 当前知识库成员角色 owner/editor/viewer |
| `KbVectorSearchPage` | 删除 | 不迁移 RAG 检索 |
| `KbExtractionConfigPage` / `KbPromptEditorPage` / `KbRuleGroups` / `KbScriptManager` / `KbGlobalConfig` / `KbResourcesPage` | 删除 | 当前产品不做抽取配置编辑 |
| `KbGlossaryPage` / `KbGlossaryEditorPage` | 删除 | 由“业务词典”替代 |
| `KbPlaceholderPage`（图谱/问答） | 删除 | 不迁移 RAG |
| `IntegrationTaskResultPage` | 删除 | 用 `/share/:token` 只读分享页替代 |
| `WorkspacesPage` | 保留 + 适配 | 当前工作空间、成员、邀请 |
| `InvitationsPage` | 改造/删除 | 当前只有工作空间邀请，无“我的邀请”；建议放进工作空间详情 |
| `ApiKeysPage` | 保留 + 适配 | 当前 API Key 作用域与知识库白名单 |
| `UsersPage`（admin） | 保留 + 改造 | 当前 admin/user 两角色；删除角色/权限矩阵列 |
| `RolesPage` | 删除 | 当前无 RBAC 权限矩阵 |
| `AuditLogsPage` | 保留 + 适配 | 当前审计字段：actor/action/target/detail |
| `PendingPage` | 删除 | 无审批流 |
| `KbExtractionStandaloneLayout` | 保留 | 分享页只读模式复用 |
| `TestPanel` / `rbac` store 中权限码逻辑 | 删除/简化 | 改为当前角色判断 |

### 新增（原前端没有、当前产品需要）

| 新增项 | 说明 |
| --- | --- |
| 业务词典页 | 当前 `/v1/business-dictionary`：类别/项目/方法、别名、pending 条目、同步 |
| 抽取详情“复核”面板 | 字段风险、接受/修正/拒绝、批量接受低风险、提交/确认锁定 |
| 抽取详情“新词”面板 | 接受/映射/拒绝，回流业务词典 |
| 抽取详情“证据”面板 | 证据页码/表/行/列/引用，跳转原文定位 |
| 分享页 `/share/:token` | 只读 Schema 结果 + 导出，15 分钟签名令牌 |
| 导出/分享按钮 | hanson JSON、JSON、CSV、XLSX、生成分享链接 |
| 结果版本历史 | 当前 `review_version` / 多次解析；需要后端补版本列表 |
| Schema 结果元数据 | 供 UI 定位证据的 record_id/property/evidence_id 映射，不影响交付 JSON |

## 4. 目标路由

```text
/login
/                        工作台
/profile                 个人中心
/kb                      知识库列表
/kb/:kbId                知识库概览
/kb/:kbId/documents      文档解析
/kb/:kbId/extraction     结构化抽取列表
/kb/:kbId/extraction/:docId   抽取详情（核心）
/kb/:kbId/tasks          任务列表
/kb/:kbId/members        知识库成员
/kb/:kbId/documents/:docId/viewer   原文查看
/dictionary              业务词典
/workspaces              工作空间
/workspaces/:id          工作空间详情（成员/邀请）
/api-keys                API Key
/users                   用户管理（admin）
/audit                   审计日志
/share/:token            分享结果（只读）
```

兼容：保留 `/jobs/:jobId` 重定向到 `/kb/:kbId/extraction/:docId`，避免旧链接失效；旧 `/kb/:kbId/extractions` 重定向到新抽取列表。

## 5. 前端改造方案

### 5.1 设计系统与壳层（直接复用）

从原项目复制并保持：

- `layouts/AppShell.tsx`：侧边栏、用户菜单、顶部标题、移动端导航
- `styles/globals.css`：浅绿主题 token、字体、阴影、aurora/doc-grid/动效
- `components/ui/*`：button/card/dialog/input/label/select/table/tabs/toast/badge/pagination/skeleton/spinner/switch
- `components/PageHeader.tsx`、`StatCard.tsx`、`PasswordStrengthMeter.tsx`
- `lib/utils.ts`（cn、formatDateTime、generateTraceId 等）
- `main.tsx` 的 QueryClient + ToastProvider + RouterProvider 结构

替换当前 `apps/web/src/styles.css`、`components.tsx`、`navigation.tsx`、`VirtualTable.tsx` 等自研样式/组件。

### 5.2 技术栈与依赖调整

`apps/web/package.json` 增加：

- `@tanstack/react-query`、`axios`、`zustand`、`lucide-react`
- `class-variance-authority`、`clsx`、`tailwind-merge`
- `@fontsource-variable/geist`、`@fontsource-variable/geist-mono`
- 可选：`recharts`（仅工作台图表需要时保留）

路由版本：当前 React Router 7.9 可用，但原代码按 6.30 编写；建议**锁定 6.30** 降低迁移风险。Tailwind 4 保持。

### 5.3 API 适配层

原 `api/client.ts` 需要改：

- `baseURL` 从 `/api/v1` 改为 `/v1`
- 去掉 `{code,data}` 解包，直接返回 response data
- 去掉 refresh token 逻辑（当前只有 access token）
- 401 统一清理 token 并跳转 `/login`
- 保留 trace id（可选）

新增 `api/adapters.ts`，把当前 DTO 映射为原页面期望结构：

| 原前端字段 | 当前后端 | 映射 |
| --- | --- | --- |
| `User.full_name` | `display_name` | 直接映射 |
| `User.is_superuser` | `role === "admin"` | 布尔映射 |
| `KbItem.my_role` | `KnowledgeBaseOut.role` | 字段改名 |
| `KbItem.member_count` | 需后端补 | 见 6.1 |
| `DocumentItem.filename` | `file_name` | 字段改名 |
| `DocumentItem.status=parsing` | `queued/running` | 状态映射 |
| `DocumentItem.file_size` | 需后端补 | 见 6.1 |
| `DocumentItem.page_count` | 需后端补 / 任务 summary | 见 6.1 |
| `ExtractionResult.categories` | `/result/schema` | 已对齐，直接使用 |
| `Task.status/progress` | `/v1/tasks` | 直接使用 |
| `AuditLog` | `actor_id/action/target/detail` | 字段映射 |

### 5.4 抽取详情页改造（重点）

原 `KbExtractionDetailPage` 是产品核心，改造点：

1. **去掉 Schema 选择区**：当前只有“产品标准抽取模板”，改为固定展示 `schema_name` 和类别数。
2. **开始/重新抽取**：调用当前 `/v1/documents/{id}/parse`；状态来自 `/v1/tasks/{job_id}`，显示 stage/progress。
3. **结果读取**：`GET /v1/documents/{id}/result/schema`，直接渲染 `categories[].records`；表格列使用 category 内字段并集。
4. **编辑单元格**：不新增批量覆盖接口，改为调用当前字段复核 `POST /v1/documents/{id}/field-reviews`（action=edit），保留审计与版本。
5. **字段复核面板**：接 `/review-risks`、`/field-reviews`、`/field-diff`；保留接受/修正/拒绝/批量接受低风险。
6. **新词面板**：接 `/new-terms`、`/new-terms/review`，显示 pending 数量，确认锁定前必须清零。
7. **证据定位**：通过 `/evidence` + `/pages/{no}/image` 跳转；记录到证据的映射由 `?with_meta=1` 返回（见 6.3）。
8. **历史版本**：接新增 `/result/versions`；点击只读查看历史结果，不覆盖当前草稿。
9. **导出/分享**：`hanson/json/csv/xlsx` + `/share`；分享页复用只读布局。
10. **复核锁定**：提交复核/确认复核按钮接当前 `/review` 接口；锁定后只读。
11. **裁剪**：去掉 `hit_score`、`recall`、`retried`、Schema 切换、删除类别/新增记录等原抽取配置能力（当前结果结构不包含这些字段）。

### 5.5 文档页与查看器

- 上传：当前 `.pdf/.md`，最大 100 MB；上传后状态 `uploaded`。
- 操作：开始解析 / 重新解析 / 删除 / 预览。
- 状态：`uploaded/queued/running/succeeded/review/failed` 映射为原页面徽章；“解析中”显示阶段与百分比。
- 查看器：复用原双栏 PDF + 页图 + 证据定位，接当前 `/preview`、`/pages/{no}/image`、`/evidence/{id}`。

### 5.6 后台与管理页

- 工作空间：保留列表/详情/成员/邀请；邀请只保留工作空间邀请。
- API Key：保留创建/撤销/作用域/知识库白名单。
- 用户管理：只保留 admin/user 角色、启用/停用、重置密码；删除角色/权限矩阵。
- 审计日志：字段适配 actor/action/target/detail；支持按动作筛选。
- 业务词典：新建页面，接 `/v1/business-dictionary`、`/sync`、`/aliases`、`/pending`。
- 工作台：改为知识库数、文档数、解析任务数、待复核数、最近任务列表；去掉 RAG 图表与问答统计。

## 6. 后端补口清单（只读为主）

| # | 接口/字段 | 用途 | 改动 |
| --- | --- | --- | --- |
| 6.1 | `DocumentOut` 增加 `file_size`、`page_count`、`latest_schema_name`、`history_count` | 文档列表/卡片展示 | 文件 stat + 任务 summary + DocumentTask 计数 |
| 6.2 | `KnowledgeBaseOut` 增加 `member_count` | 知识库卡片/详情 | 成员表计数 |
| 6.3 | `GET /v1/documents/{id}/result/schema?with_meta=1` | UI 证据定位 | 在现有投影结果旁返回 `meta`：record_id/property/evidence_id/page_no；默认不返回，保持交付 JSON 干净 |
| 6.4 | `GET /v1/documents/{id}/result/versions` | 历史版本 | 列出 job_id/version/status/created_at/schema_name/category_count/record_count |
| 6.5 | `GET /v1/dashboard` | 工作台概览 | 聚合 KB/文档/任务/待复核/最近任务；避免前端多次请求 |
| 6.6 | `GET /v1/documents/{id}/result/schema`（已有） | 结果页 | 无需改；复核后的记录需继续生效 |

不改：认证、抽取链路、Schema 投影规则、导出/分享、字段复核、新词、业务词典、API Key、审计。

## 7. 分阶段实施计划

### P0 基线冻结与审计

- 从 `.75` 只读取前端源码快照到本地特性分支（原项目不改）。
- 建立页面清单、API 调用清单、路由清单、依赖清单。
- 安全审计：删除无鉴权 integration 页面；检查文件预览/XSS/越权；确认所有页面走当前鉴权。
- 产出：`docs/frontend-inventory.md`（页面/API/依赖/取舍）。

**验收**：清单完整；无安全阻断项；确认保留/删除/新增清单。

### P1 壳层、登录、API 适配

- 替换 `main.tsx`、`AppShell`、`globals.css`、`components/ui/*`、`lib/utils`。
- 改写 `api/client.ts` 与 `stores/auth.ts`；新增 `api/adapters.ts`。
- 登录页接 `/v1/auth/login`、`/v1/auth/me`；个人中心接 profile/password。
- 保留 403/404；删除 pending 审批页。

**验收**：登录/退出/刷新页面正常；`tsc --noEmit` 通过；页面视觉与原项目一致。

### P2 知识库与文档

- `KnowledgeBasesPage`、`KbDetailLayout`、`KbOverviewPage`、`KbDocumentsPage`、`KbTasksPage`、`KbMembersPage`、查看器。
- 导航裁剪为 5 项；文档上传/解析/重解析/删除；状态映射；成员角色。
- 接 6.1、6.2 补口。

**验收**：创建知识库、上传 PDF、解析、查看任务、删除文档全链路通过；浏览器无 console error。

### P3 结构化抽取列表与详情（核心）

- `KbStructuredExtractionPage` 改为当前文档/任务入口。
- `KbExtractionDetailPage` 按 5.4 改造：单模板、Schema 结果、复核、新词、证据、历史、导出、分享、锁定。
- 接 6.3、6.4；分享页 `/share/:token`。
- 去掉原 Schema/Prompt/Rule/Script/Glossary/Vector/Graph/QA 路由与组件。

**验收**：上传→解析→结果→复核→确认→导出→分享 全链路通过；证据可定位；字段修正后导出生效；历史版本可查看。

### P4 管理页与业务词典

- 工作空间/邀请、API Key、用户管理、审计日志、业务词典、工作台。
- 删除角色管理、RBAC 权限矩阵、集成结果页、待审批页。
- 接 6.5。

**验收**：6 个管理页正常；业务词典别名/pending/同步可用；工作台数据来自真实接口。

### P5 清理与替换

- 删除旧 `apps/web/src/pages/*`、旧 `components.tsx`、`navigation.tsx`、`VirtualTable.tsx`、`styles.css`。
- 清理旧 API 模块与依赖；统一路由重定向。
- 全量 `rg` 检查无 RAG/配置/术语集/角色矩阵残留。

**验收**：无死路由、无未使用依赖、无旧页面引用；构建产物只包含目标页面。

### P6 测试与发布

- `tsc --noEmit`、`vite build`、Vitest 页面测试。
- Playwright E2E：登录/KB/上传/解析/结果/复核/新词/导出/分享/管理页。
- 视觉回归：与原项目截图对比主要页面（登录、KB 列表、文档页、抽取详情、工作台）。
- 构建 `hanson-r1-web:r6-13`，保留 `r6-12` 回滚；部署后 `nginx -s reload`。

**验收**：E2E 全通过；无 5xx/console error；关键页面与原项目视觉一致；可回滚。

## 8. 验收标准（整体）

1. 页面与交互以 hansonDoc_RAG 为基线，不出现当前自研的顶部横栏 + 卡片堆叠风格。
2. 目标页面全部可用：登录、工作台、KB、文档、抽取列表/详情、任务、成员、查看器、工作空间、API Key、词典、用户、审计、分享。
3. 无用模块 0 残留：向量搜索、问答、图谱、抽取配置、专业术语集编辑器、角色矩阵、审批、集成结果页。
4. 抽取详情：Schema 结果、缺失字段、复核、新词、证据、历史、导出、分享、锁定全部可用。
5. 后端无新增写接口（除必要的字段/查询接口）；所有编辑走字段复核审计。
6. 浏览器：无 pageerror、无 console error、无 5xx；上传/解析/导出/分享实测通过。
7. 移动端/窄屏可操作；PDF 预览与证据定位正常。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 原前端 API 契约与当前后端不一致 | 页面无法加载 | 适配层 + 类型断言 + 每页联调；先做 API 冒烟 |
| 原前端依赖 RBAC 权限码 | 页面按钮/路由被误拦截 | 删除 `rbac` store，改为当前 role/成员判断 |
| 原页面包含无鉴权 integration 路由 | 安全回归 | 不迁移该路由；分享统一走 HMAC token |
| 结果编辑直接覆盖 | 丢失审计 | 单元格编辑写入 field-review edit 事件，不新增批量覆盖接口 |
| 历史版本接口缺失 | 历史弹窗不可用 | 先做只读版本列表接口 6.4；无数据时展示空态 |
| 文档列表缺 file_size/page_count | 列表信息不全 | 后端补 6.1；前端先做容错显示 |
| React Router/Tailwind 版本差异 | 编译/样式异常 | 锁 React Router 6.30；Tailwind 4 与主题 token 原样复制 |
| 一次迁移页面过多 | 回归范围大 | 按 P1–P4 分阶段，每阶段独立验收 |
| 字体/图标离线 | 内网加载失败 | 字体自托管（@fontsource）；lucide 本地打包 |

## 10. 本次不做

- RAG 检索、知识问答、知识图谱、向量搜索。
- Schema/Prompt/规则组/脚本/资源与配置编辑。
- 专业术语集编辑器（由业务词典替代）。
- 角色/权限矩阵、审批流、集成任务展示页。
- 抽取模型、OCR、编排逻辑变更。

## 11. 已确认决策（2026-11-06）

| 决策项 | 结论 |
| --- | --- |
| 迁移方式 | **替换式迁移**：以原 hansonDoc_RAG 前端为基线，最终删除当前自研页面，只保留一套 UI |
| 结果编辑 | **字段复核事件**：单元格编辑写入现有 `field-review` 事件，保留审计与版本，不新增整表覆盖接口 |
| 历史版本 | **需要**：补只读结果版本接口，详情页可查看历次解析/复核版本 |
| 工作台 | **统计卡片 + 最近任务**：去掉 RAG 图表，聚焦知识库/文档/解析/待复核 |

上述决策已纳入第 5–7 节，作为实施基线。

## 12. 实施结果（2026-11-06）

已完成 P0–P6 主体验收：

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P0 基线审计 | 完成 | 从 `192.168.188.75` 只读拉取原前端源码；确认保留/删除/新增清单 |
| P1 壳层与适配 | 完成 | `AppShell`、浅绿主题、`components/ui`、登录、401 处理、`/v1` API 适配层 |
| P2 知识库与文档 | 完成 | 知识库列表/概览/文档解析/任务/成员/原文查看；文档列表补 `file_size/page_count/member_count` |
| P3 抽取列表与详情 | 完成 | 单模板结果、类别折叠表格、JSON 视图、原文页预览、字段复核、新词、历史版本、4 种导出、分享、锁定 |
| P4 管理页 | 完成 | 工作台（统计卡片+最近任务）、业务词典、工作空间、API Key、用户管理、审计日志 |
| P5 清理 | 完成 | 删除旧 `pages/*`、旧组件、向量搜索/问答/图谱/抽取配置/术语集编辑器/角色矩阵/审批/集成结果页 |
| P6 验证与发布 | 完成 | `tsc --noEmit`、`vite build`、Playwright 冒烟与主链路、`hanson-r1-web:r6-13`、`platform-api:r6-13`；知识库词典追加后升至 `r6-14` |

后端补口：

- `DocumentOut` 新增 `file_size`、`page_count`、`latest_schema_name`、`history_count`。
- `KnowledgeBaseOut` 新增 `member_count`。
- 新增 `GET /v1/documents/{id}/result/versions`（只读历史版本）。
- 分享 bundle 增加 `schema`，分享页直接渲染结构化结果。

知识库级业务词典（2026-11-06 追加）：

- 词典落盘为 `/data/engine/dictionaries/{kb_id}.json`；创建知识库时从全局 `configs/business_dictionary.hanson.json` 复制种子，之后各知识库独立演进。
- 解析任务 options 携带 `dictionary_path`，`runner.py` 覆盖本次 job 的 `business_dictionary_path`，对齐、新词与 `schema_result.json` 投影都使用该知识库词典。
- 新增 `GET /v1/knowledge-bases/{kb_id}/dictionary`、`GET .../dictionary/pending`、`POST .../dictionary/aliases`；新词接受/映射写回该知识库词典，不再写全局 override。
- 前端“业务词典”从全局导航移入知识库内部导航（`/kb/:kbId/dictionary`），支持按类型/名称/别名检索和别名维护；工作台不再提供全局词典入口。
- Schema 投影、导出与分享接口在生成 hansonDoc 结构时传入知识库词典索引，历史文档无词典文件时回退全局词典。

浏览器实测（`docs/frontend-migration-2026-11-06/`）：

- 登录、工作台、知识库、概览、文档解析、结构化抽取、业务词典、工作空间、API Key、用户、审计：全部渲染正常，0 console/page error。
- TA15 文档：上传 → 解析（12 页 / 6 表 / 4 记录）→ 抽取详情（13 类别 / 26 条记录）→ Schema JSON 导出（10,057 字节）→ 分享页只读渲染，全部通过。
- 知识库词典隔离：临时 KB 添加别名后仅本 KB 命中（1 条），其他 KB 命中 0 条；`/kb/<id>/dictionary` 页面表格与别名按钮渲染正常。
- 发布：`hanson-r1-platform-api:r6-14`、`hanson-r1-engine-api:r6-14`、`hanson-r1-worker-prod/explore:r6-14`、`hanson-r1-web:r6-14`，全部 healthy。

已知事项：

- 2026-11-06 模型机 `192.168.188.75` 上 GLM-OCR、Layout、Qwen 进程曾全部退出；已按原参数重启（GLM seq12/batched8192/gpu0.4，Qwen adapter-v5:9991）。解析在模型不可用时会快速返回 0 表 0 记录，需先确认四个端口 200。
- 抽取详情页原文预览为逐页图片 + 页码切换，完整 PDF 连续预览保留在「放大查看」的查看器中。
- 既有知识库的词典文件是创建/首次访问时从全局种子复制，当前内容相同但文件独立；后续别名与新词只影响各自知识库。

## 13. 结构化抽取质量修复（2026-11-06）

使用 `192.168.188.75` 的真实模型服务（GLM-OCR `9977`、Layout `9979/9978`、Qwen `9991`）重新走了全流程：上传 → OCR/Layout → 表格与条款抽取 → 业务词典对齐 → hansonDoc Schema 投影 → 前端展示 → 导出。

发现并修复：

- **标准名称误取章节标题**：原逻辑按词频/长度挑选前 3 页标题，GB/T 3191 被选成 `4.1.1 牌号、状态、规格`。改为按“产品词 + 页码 + CJK + 编号惩罚 + 模板词惩罚”打分，并对 `TA15 钛合金锻制棒材` 做中西文空格归一化；无候选项时从文件名去上传前缀/标准号兜底。
- **多行表头误判**：GB/T 3191 表6 首行数据被当成表头（`牌号 | 1060`），TA15 表3 的两行表头被压成一行。调整 `_looks_like_range_header` 与 `_detect_header_rows`：首列为纯数字视为数据行；数据行优先于范围表头；续页表正确合并（表6 由 41 行合并）。
- **试验方法缺失**：新增“方法条款 + 引用标准标签”匹配，按 item family 关键词从 `5.x 试验方法` / `引用标准` 中提取 `GB/T 228`、`GB/T 6987`、`GB/T 6395`、`GB/T 3247` 等；优先 `方法` 命名条款，避免把“应符合 GB/T 3190”当试验方法。
- **持久性能表未投影**：新增按 `牌号/温度/应力/保持时间` 表头识别持久表，生成“持久强度”行（TA15 表3：500℃、470MPa、≥50h；GB/T 3191 表8：2A02/2A16 三行）。
- **冲击列未识别**：`canonical_property` 增加 `AK/AKV → KV2`；修掉 impact 项把同表 Rm/A/HB 也当冲击属性的问题，按 family 过滤属性。
- **定性项目标准要求为空**：低倍/高倍/外观从对应条款及子条款回填；尺寸/弯曲用表题回填“应符合表X的规定”；GB/T 3191 的化学成分是引用条款，新增“化学成分（全部牌号，GB/T 6987）”行。
- **前端列缺失**：投影结果增加 `category.fields`（标准信息 2 列、项目 13 列、热处理 12 列），前端表格按 `fields` 渲染完整列，不再依赖记录键并集；导出 hansonDoc JSON 时移除 `fields`，保持原 Schema 形状。
- **尺寸厚度丢失**：从 `H112 / ≤150 / 纵向` 这类组合条件中逐段识别厚度，不再只看第一段。

真实测试结果：

| 文档 | 标准信息 | 类别/记录 | 关键验证 |
| --- | --- | --- | --- |
| GB/T 3191-1998 铝及铝合金挤压棒材 | 铝及铝合金挤压棒材 / GB/T 3191-1998 | 8 类 / 92 条 | 室温拉伸 82 条、试验方法 GB/T 228-87、13 列完整；化学成分/持久/低倍/高倍/尺寸/弯曲均有值 |
| Q/S 10-0351-2004 TA15钛合金锻制棒材 | TA15钛合金锻制棒材 / Q/S 10-0351-2004 | 13 类 / 26 条 | 冲击为“冲击吸收能量 ≥28J”；持久为“500℃ / 470MPa / ≥50h”；试验方法齐全 |

验证与发布：

- 引擎测试 36 通过（schema projection / tablegrid / repairs / normalize）。
- 平台 API 测试 55 通过；2 个 Windows 临时目录清理 `WinError 32` 为既有环境抖动，与本次改动无关。
- 浏览器实测两个文档：标准信息、13 列表格、试验方法、化学成分、持久强度均正常显示。
- 发布：`hanson-r1-platform-api:r6-19`、`hanson-r1-engine-api:r6-19`、`hanson-r1-worker-prod/explore:r6-19`、`hanson-r1-web:r6-16`。

仍存在：

- TA15 的“尺寸”“β转变温度”在原文中未给出可直接引用的要求条款，保留为空并标记缺失。
- GB/T 3191 化学成分条款 OCR 文本截断为“应符合GB/T 319”，已原样保留，未凭空补全标准号。

