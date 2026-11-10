# 模块处置清单（M1.9a）

> 日期：2026-10-27
> 状态：v0.1（待审计收口）
> 输入：`docs/hansonDoc_RAG-audit.md`、`docs/frontend-scope.md`、`docs/frontend-modification.md`
> 审计对象：hansonDoc_RAG commit `c74ea91`（原 188.75，现部署于 1.35；只读，不修改远端）

---

## 1. 处置口径

| 处置 | 含义 | 进入当前项目的条件 |
|---|---|---|
| 迁移 | 代码基本可用 | 审计问题修复 + 单元/契约测试通过 |
| 改造 | 思路可用，需裁剪 | 去除旧耦合 + 补测试 |
| 重写 | 接口/契约保留，代码重写 | 契约评审通过 |
| 删除 | 不进入当前项目 | 全局搜索无引用、依赖移除 |

统一目标目录（M1.9 迁移完成后）：

```text
packages/engine     解析、TableGrid、配方、项目清单、条款、业务对齐
packages/parsers    parsekit 改造版
packages/adapters   模型、业务词典、对象存储
packages/knowledge  业务词典/别名
apps/api            认证、知识库、文档、任务、结果、复核、词典
apps/worker         解析/拆分/词典同步任务
apps/web            React 前端
```

当前阶段引擎仍在 `metal-doc-agent/`；先做平台侧，不做大规模搬目录。

---

## 2. 后端模块

| 模块 | 源路径 | 处置 | 目标 | 审计重点 | 当前状态 |
|---|---|---|---|---|---|
| parsekit | `backend/app/services/parsekit/` | 迁移 | `packages/parsers` | 并发、失败语义、文本层双源、产物契约 | 待迁移审计 |
| 文档模型/服务 | `models/document.py`、`services/document_service.py` | 迁移 | `apps/api/documents` | 状态机、删除/清理、幂等 | 待迁移审计 |
| 任务/Outbox/arq | `backend/app/tasks/`、Outbox/DLQ | 迁移 | `apps/worker`、`apps/api/tasks` | 重试、心跳、事务边界、状态回写 | 待迁移审计 |
| 存储 | `services/storage.py` | 迁移 | `packages/adapters/storage` | 对象键、越权、生命周期 | 待迁移审计 |
| RBAC/审计 | `services/rbac_service.py`、`security.py`、`middleware/audit_log.py` | 迁移 | `apps/api/auth` | RLS 绕过、审计完整性、越权 | 待迁移审计 |
| 知识库/工作空间/群组 | `models/knowledge_base.py`、`workspace.py`、`services/kb_service.py` | 迁移 | `apps/api/knowledge` | RLS、成员/群组授权、邀请 | 待迁移审计 |
| API Key | `models/api_key.py`、相关服务 | 迁移 | `apps/api/api_keys` | 哈希、作用域、撤销、审计 | 待迁移审计 |
| 术语集 | `models/glossary.py`、`services/glossary/` | 改造 | `packages/knowledge` + `apps/api/dictionary` | 同步语义、pending/active、误合并 | 已由引擎快照替代，平台侧待接 |
| integration | `api/v1/endpoints/integration.py`、`services/integration_service.py` | 重写 | `apps/api/standard_extractions` | 认证、幂等、限流、错误码 | 引擎 API 已先行，平台入口待写 |
| LLM 客户端 | `services/llm/llm_client.py` | 迁移 | `packages/adapters/llm` | 超时、重试、并发、JSON | 待迁移审计 |
| 抽取 V3 | `services/extraction/pipeline.py`、`category_builder*.py` | 删除 | — | 41 类检索式，不符合标准拆分 | 不迁移 |
| `table_to_rows` | `services/extraction/table_to_rows.py` | 删除 | — | 不展开 rowspan/colspan | 不迁移 |
| chunker/retrieval | `services/indexing/` | 删除 | — | 本期不做 RAG | 不迁移 |
| RAG/图谱 | 占位/旧版 | 删除 | — | 不属于标准拆分 | 不迁移 |

---

## 3. 前端模块

| 页面/模块 | 处置 | 目标路由 | 说明 |
|---|---|---|---|
| 登录/个人中心 | 迁移 | `/login`、`/profile` | 审计认证流程 |
| 知识库列表/概览 | 迁移 | `/kb`、`/kb/:id` | 保留成员/空间 |
| 文档列表/上传 | 迁移+改造 | `/kb/:id/documents` | 增加标准拆分任务类型与状态 |
| 文档内页/预览 | 迁移+改造 | `/kb/:id/documents/:docId/viewer` | 增加项目/记录/条款/证据标签 |
| 任务列表 | 迁移+改造 | `/kb/:id/tasks` | 引擎阶段、缺口、重试 |
| 标准拆分列表 | 改造 | `/kb/:id/extraction` | 由旧抽取列表改造 |
| 拆分结果详情 | 改造 | `/kb/:id/extraction/:docId` | 项目/记录/条款/证据/新词 |
| 独立结果页 | 改造 | `/extraction/:kbId/:docId` | 短期令牌，不允许长期无鉴权 |
| 业务词典 | 改造 | `/kb/:id/business-dictionary` | 替代旧术语集页，允许别名/pending |
| 成员/邀请 | 迁移 | `/kb/:id/members`、`/kb/invitations` | 保留 |
| 工作空间/群组 | 迁移 | `/workspaces` | 保留 |
| API Key | 迁移 | `/api-keys` | 保留 |
| 用户/角色/审计 | 迁移 | `/admin/*` | 保留 |
| 项目清单/记录/条款/证据 | 新建 | 文档内页标签 | 已在骨架中验证 API |
| 旧术语集编辑器 | 删除 | — | `GlossaryEditorPage`、三源/审核 UI |
| 抽取配置/Prompt/脚本 | 删除 | — | 配置化替代 |
| 向量搜索/图谱/问答 | 删除 | — | 不属于标准拆分 |

---

## 4. 删除清单（代码级）

```text
backend/app/services/extraction/pipeline.py
backend/app/services/extraction/category_builder*.py
backend/app/services/extraction/table_to_rows.py
backend/app/services/extraction/script_tools.py 中旧匹配/脚本部分
backend/app/services/indexing/
frontend/src/views/KbVectorSearchPage.tsx
frontend/src/views/KbExtractionConfigPage.tsx
frontend/src/views/KbPromptEditorPage.tsx
frontend/src/components/KbRuleGroups.tsx
frontend/src/components/KbScriptManager.tsx
frontend/src/views/KbGlobalConfig.tsx（或改只读）
frontend/src/api/modules/extractionConfig.ts
frontend/src/api/modules/indexing.ts
frontend/src/api/modules/glossary.ts 中 api/db 三源与审核部分
```

删除验收：

- 全局搜索无路由/组件/API 引用；
- `pnpm build`、`tsc --noEmit` 通过；
- 菜单/权限点清理；
- E2E 主链路不依赖被删页面。

---

## 5. 迁移顺序（主链路优先）

```text
P0  认证 + 知识库 + 文档上传/列表 + 任务中心
P1  解析 worker（parsekit）+ 文档预览
P2  引擎拆分入口（standard-extractions）+ 项目/记录/条款/证据
P3  新词确认 + 业务词典 + 复核
P4  删除旧模块 + 权限/审计收口 + 部署
```

每一步的退出条件：

| 阶段 | 退出条件 |
|---|---|
| P0 | 登录 → 建知识库 → 上传文档 → 任务可见 |
| P1 | 解析完成，页图/版面/文本可回读 |
| P2 | 拆分完成，项目/记录/条款/证据可查，证据可定位 |
| P3 | 新词可确认并回流，词典版本可追溯 |
| P4 | 删除项无残留，安全/权限通过，三平面部署 |

---

## 6. 审计门状态

| 编号 | 问题 | 严重度 | 状态 | 关闭条件 |
|---|---|---|---|---|
| A1 | integration 端点无认证、superuser 绕过 RLS | S1 | 已关闭（P0） | 平台端点 JWT/API Key + 成员校验；无 superuser；可选引擎令牌 |
| A2 | 独立结果页无登录保护 | S1 | 已关闭（P0） | 15 分钟 HMAC 分享令牌，过期/篡改 401 |
| A3 | `return_type=object` 未实现 | S2 | 随旧抽取删除 | 不迁移 |
| A4 | `table_to_rows` 不展开合并单元格 | S2 | 随旧抽取删除 | 不迁移 |
| A5 | 大表 chunk 切碎 | S1（业务） | 随检索式删除 | 不迁移 |
| A6 | 41 类固定类别 | S2 | 随旧抽取删除 | 不迁移 |
| A7 | `match_record` 语义优先/阈值硬编码 | S2 | 已由引擎匹配器替代 | — |
| A8 | 术语集同步丢审核状态 | S2 | 改造中 | 版本化 + 差异同步 + pending 保留 |
| A9 | 任务失败/重试状态不一致 | S2 | 已完成 | 状态机 + 抢占 + 过期回收 + 锁定重试测试 |
| A10 | 依赖未锁定 | S2 | 部分完成 | 直接依赖已锁定；扫描待 CI |
| A11 | 前端无单元测试 | S3 | 待补 | 关键组件测试 + E2E |
| A12 | RLS/多租户复杂 | S3 | 保留不裁剪 | 迁移审计 |
| A13 | OCR 失败语义不统一 | S3 | 待复核 | 统一错误码 |
| A14 | 前端大页面耦合旧配置 | S3 | 改造中 | 拆分标签页/移除旧配置 |

进入 M1.9 代码迁移前，A1、A2、A5 必须有明确处理方案（重写/删除/隔离）；其余项可随迁移修复。

---

## 7. 明确不迁移

- 41 类检索式抽取与类别构建；
- `table_to_rows`、chunker、BM25/向量检索、RAG/图谱/问答；
- 旧抽取配置、Prompt 编辑器、规则组/脚本执行器；
- 旧术语集 api/db 三源编辑器、批量编辑、审核流；
- 任何依赖“检索窗口决定抽取完整性”的逻辑。
