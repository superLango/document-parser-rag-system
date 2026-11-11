# 前端优化改造方案

> 阶段：M1.9a → M1.9
> 状态：draft v0.1
> 日期：2026-10-27
> 约束：188.75 原项目只读；改造在当前项目 `f:\hanson\hanson_doc_parse` 内进行。

---

## 1. 改造目标

在 hansonDoc_RAG 前端基础上做取舍，不是全量重写：

- 保留：登录、知识库/成员/工作空间/群组/邀请、API Key、文档、预览、任务、权限、审计；
- 改造：抽取列表/详情 → 标准拆分；术语集 → 业务词典（允许人工别名/pending）；复核单角色；
- 新建：项目清单、记录、条款、证据、新项确认；
- 删除：抽取配置、Q&A/图谱/向量搜索、旧术语集多源编辑。

---

## 2. 全局框架

### 2.1 路由

保留：

```text
/login
/
/profile
/help
/about
/kb
/kb/invitations
/workspaces
/api-keys
/kb/:kbId
/kb/:kbId/documents
/kb/:kbId/documents/:docId/viewer
/kb/:kbId/tasks
/kb/:kbId/extraction            → 标准拆分列表
/kb/:kbId/extraction/:docId    → 拆分结果详情
/extraction/:kbId/:docId       → 独立结果页
/admin/users /admin/roles /admin/audit-logs
```

删除：

```text
/kb/:kbId/vector-search
/kb/:kbId/graph
/kb/:kbId/qa
/kb/:kbId/extraction-config
/kb/:kbId/extraction-config/prompts/:promptId
/kb/:kbId/glossary              → 由 /business-dictionary 替代
/kb/:kbId/glossary/:baseId      → 由 /business-dictionary 替代
```

新增：

```text
/kb/:kbId/documents/:docId/items
/kb/:kbId/documents/:docId/records
/kb/:kbId/documents/:docId/clauses
/kb/:kbId/documents/:docId/new-terms
/kb/:kbId/business-dictionary
```

### 2.2 菜单

知识库内部菜单调整为：

```text
概览
文档解析
标准拆分
业务词典
任务列表
成员
审计（如需要）
```

删除：向量搜索、知识图谱、知识问答、抽取配置、旧术语集入口。

### 2.3 状态与请求

- 保留 React Query + Zustand 模式；
- 新增 query key：`items`、`records`、`clauses`、`evidence`、`new-terms`、`dictionary`；
- 任务轮询复用现有 2s 轮询，增加引擎阶段；
- 错误态展示缺口/冲突/未映射，不只显示“失败”。

---

## 3. 页面改造明细

### 3.1 文档列表 `KbDocumentsPage.tsx`

改造点：

- 任务类型增加 `standard_extraction`；
- 状态列增加“解析中/拆分中/待复核/完成/失败”；
- 操作：开始解析、重新解析、开始拆分、查看结果、删除；
- 顶部增加筛选：文档类型、状态、是否有新项。

验收：上传→解析→拆分状态可追踪。

### 3.2 文档内页 `KbDocumentViewerPage.tsx`

改造点：

- 右侧标签由“版面块 / Markdown / JSON”扩展为：
  `项目清单 / 记录 / 条款 / 证据 / Markdown / 版面块 / JSON`；
- 增加证据高亮：点击记录值定位页码/表/行/列；
- 保留 PDF 翻页与版面框联动；
- 证据抽屉显示 quote、表 ID、行列、OCR/文本层来源。

验收：任一记录值可回读原文。

### 3.3 标准拆分列表 `KbStructuredExtractionPage.tsx`

改造点：

- 标题/文案改为“标准拆分”；
- 列：文档、解析状态、拆分状态、项目数、记录数、new 项数、更新时间；
- 操作：开始拆分、查看结果、重新拆分；
- 不再选择 Schema/类别；改为显示配方/词典版本（只读）。

### 3.4 拆分结果详情 `KbExtractionDetailPage.tsx`

改造点：

- 顶部：文档名、状态、配方版本、词典版本；
- 标签页：项目清单 / 记录 / 条款 / 证据 / 新项；
- 项目清单表：项目名、family、facets、status、方法、证据、筛选；
- 记录表：牌号 × 条件 × 属性；分组展开；
- 条款表：方法/方向/位置/数量/温度/判定；
- 新项：确认/改名/映射到已有/拒绝；
- 保留历史版本/重新拆分（如已有）。

验收：一页看完“有哪些项目、抽了什么、证据在哪、哪些是新的”。

### 3.5 业务词典 `KbGlossaryPage.tsx` / `KbGlossaryEditorPage.tsx` → `KbBusinessDictionaryPage.tsx`

改造点：

- 由“术语集”改为“业务词典”，路由统一为 `/kb/:id/business-dictionary`；
- 列表：业务编码、名称、类型（项目/方法）、family/facets、别名、状态、版本；
- 操作：同步业务系统、搜索、查看别名、pending 确认；
- 删除：api/db 三源向导、批量编辑、审核流、手动新增整库；
- 保留：只读同步结果、别名维护、pending→active（允许人工新增别名/pending）。

验收：业务词典可同步、可查、可确认；不再出现旧 `/glossary` 入口。

### 3.6 任务列表 `KbTasksPage.tsx`

改造点：

- 任务类型：解析/拆分/词典同步；
- 状态：queued/running/completed/failed/partial；
- 详情：阶段、进度、错误码、缺口、重试；
- 支持按文档/类型/状态筛选。

### 3.7 独立结果页 `KbExtractionStandaloneLayout.tsx` / `IntegrationTaskResultPage.tsx`

改造点：

- 保留免登录结果页思路，但必须使用短期令牌/签名，不能长期无鉴权；
- 展示项目清单/记录/证据；
- 支持导出 JSON/CSV（可选）。

### 3.8 权限/审计

- 保留登录、角色、审计；
- **知识库/成员/工作空间/群组/邀请不简化**，后续继续完善；
- 保留 API Key 页面与接口能力，用于外部对接；
- 复核单角色即可，不做多人/多角色流转；
- RBAC/RLS 迁移 + 审计，不裁剪为单项目。

---

## 4. 新建页面

### 4.1 项目清单页

```text
[文档名] [状态] [重新拆分]
筛选：family / status / 仅新项
表格：项目 | family | facets | 方法 | 状态 | 证据
点击行 → 右侧证据/记录
```

### 4.2 记录页

```text
[项目筛选] [牌号筛选] [条件筛选]
表格：牌号 | 条件 | 属性 | 值 | 单位 | 证据
点击值 → PDF/版面高亮
```

### 4.3 条款页

```text
表格：条款号 | 类型 | 方法 | 方向 | 位置 | 数量 | 温度 | 判定 | 证据
```

### 4.4 证据抽屉

```text
页码 / 表 ID / 行 / 列 / quote
[定位原文] [复制]
```

### 4.5 新项确认

```text
列表：raw | 类型 | family | facets | 建议编码 | 证据
操作：接受 | 改名 | 映射到已有 | 拒绝
```

### 4.6 业务词典

```text
搜索 / 同步 / 版本
表格：编码 | 名称 | 类型 | family | facets | 别名 | 状态
pending 条目：确认/拒绝
```

---

## 5. 删除清单

| 对象 | 处理 |
|---|---|
| `KbVectorSearchPage.tsx` | 删除文件/路由/菜单 |
| `KbExtractionConfigPage.tsx` | 删除 |
| `KbPromptEditorPage.tsx` | 删除 |
| `KbRuleGroups.tsx`、`KbScriptManager.tsx` | 删除 |
| `KbGlobalConfig.tsx` | 删除或改只读 |
| `KbPlaceholderPage` 的 graph/qa 路由 | 删除 |
| `api/modules/extractionConfig.ts`、`indexing.ts` | 删除或裁剪 |
| `api/modules/glossary.ts` 三源/审核部分 | 删除 |
| 菜单/权限点/路由常量 | 同步清理 |

删除后检查：`pnpm build`、`tsc --noEmit`、E2E 主链路、全局搜索无残留引用。

---

## 6. 前端 API 依赖（供后端完善）

| 页面 | API |
|---|---|
| 文档列表 | `GET/POST /v1/documents`、`POST /documents/{id}/parse` |
| 文档内页 | `GET /documents/{id}/preview` |
| 项目清单 | `GET /documents/{id}/items` |
| 记录 | `GET /documents/{id}/result` |
| 条款 | `GET /documents/{id}/result`（clauses） |
| 证据 | `GET /documents/{id}/evidence` |
| 新项 | `GET/POST /documents/{id}/new-terms` |
| 复核 | `POST /documents/{id}/review` |
| 业务词典 | `GET/POST /business-dictionary`、`POST /sync` |
| 任务 | `GET /tasks`、`GET /tasks/{id}` |
| 权限/审计 | 复用现有 |

---

## 7. E2E 验收

1. 上传 GB/T 40303 → 解析 → 拆分 → 项目清单含化学成分/室温拉伸 → 记录 81 元素 → 证据回读；
2. 含“按 Q/S 10-0533 规定的测试项目”的协议 → 出现跨标准任务/缺口；
3. 业务词典无“低温夏比冲击” → new 项出现 → 确认 → 回流；
4. 删除页面无路由/菜单/API 残留；
5. 1.35 只跑模型，无业务进程。

---

## 8. 风险

| 风险 | 应对 |
|---|---|
| 删除不彻底 | 依赖分析 + 全局搜索 + 构建/E2E |
| 改造范围蔓延 | 以 `frontend-scope.md` 为准 |
| 证据定位不准 | 先做只读高亮，再做编辑 |
| 旧交互惯性 | 以标准拆分主链路为准 |
| 1.35 被修改 | 只读审计；禁止部署/写入 |
