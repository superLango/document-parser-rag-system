# M7 里程碑详细执行计划：前端核心页面（new_app/web）

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2027-03-01 ~ 2027-03-21  
> 主责角色：项目负责人（兼前端）  
> 协作角色：外部业务/设计确认（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M1](M1-core-domain-orchestration.md)、[M6](M6-feedback-repair-promotion.md)  
> 当前状态：已完成（六页面 + 六 Tab，Playwright 3/3 通过，2026-11-12）

---

## 1. 里程碑目标

在 `new_app/web` 中重建标准拆分核心前端页面：

- 文档库（上传、列表、删除）。
- 标准拆分列表（审核/反馈/运行状态）。
- 解析详情（结果、审核、反馈、验证、时间线、版本、原文预览）。
- 原文预览（页图 + 版面定位）。
- 业务词典。
- 运行列表。
- 配方版本（只读 + 回滚）。

**不做**：登录、用户、工作区、成员、邀请、API Key、模块、订单、证书、外包、集成、分享、审计管理。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| 工程 | Vite + React + TS + Tailwind |
| 视觉 | 完全沿用现有产品风格规范（Q5）；提取现有 Tokens；不引入新视觉语言 |
| 路由 | 文档库、解析详情、预览、词典、运行、配方 |
| 数据层 | OpenAPI 类型 + API client + TanStack Query |
| 实时 | SSE 订阅 + 轮询兜底 |
| 组件 | 结果表、审核、反馈、验证、时间线、版本、配方依据 |
| 测试 | Vitest + Playwright E2E |
| 性能 | 首屏、表格大结果虚拟化（按需） |

### 2.2 不做

- 不迁移旧 `apps/web` 页面。
- 不做登录/权限/租户/工作区。
- 不做模块化工作台。
- 不做配方编辑器。
- 不做分享/集成结果页。
- 不引入复杂全局状态。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M1 完成 | 文档/运行 API |
| M6 完成 | 反馈/验证/晋升 API |
| M5 完成 | 审核报告 API |
| 设计基线 | 视觉风格确认（可沿用现有风格） |
| OpenAPI | 类型生成可用 |
| E2E 环境 | 隔离 DB + mock 模型/沙箱 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D7.1 | 前端应用 | `web/` | 应用 | 前端/QA |
| D7.2 | 页面 | `web/src/pages/` | 页面 | 业务/QA |
| D7.3 | 组件 | `web/src/components/` | 组件 | 前端 |
| D7.4 | API 客户端 | `web/src/api/` | 代码 | 后端 |
| D7.5 | E2E | `web/tests/e2e/` | 测试 | QA |
| D7.6 | 视觉/交互说明 | `new_app/docs/reports/M7-ui.md` | 文档 | 业务 |
| D7.7 | 前端 README | `web/README.md` | 文档 | 前端 |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M7-01 | 前端工程与设计基线 | 前端 | 业务 | 工程/主题 | 2027-03-01 |
| M7-02 | API client + 类型 | 前端 | 后端 | client | 2027-03-03 |
| M7-03 | 文档库页面 | 前端 | 后端 | 页面 | 2027-03-05 |
| M7-04 | 解析详情-结果表 | 前端 | 后端 | 结果视图 | 2027-03-08 |
| M7-05 | 审核 Tab | 前端 | Agent/QA | 审核视图 | 2027-03-10 |
| M7-06 | 反馈/验证 | 前端 | 后端 | 反馈闭环 | 2027-03-13 |
| M7-07 | 时间线/版本对比 | 前端 | 后端 | 时间线/对比 | 2027-03-15 |
| M7-08 | 预览/词典/运行/配方 | 前端 | 后端 | 页面 | 2027-03-17 |
| M7-09 | E2E + 视觉回归 | QA | 前端 | 测试报告 | 2027-03-20 |
| M7-10 | 验收 | PM | 全体 | 验收记录 | 2027-03-21 |

## 6. 页面与组件

### 6.1 路由

| 路由 | 页面 |
|---|---|
| `/` | 文档库 |
| `/documents/:id` | 解析详情 |
| `/documents/:id/viewer` | 原文预览 |
| `/runs` | 运行列表 |
| `/dictionary` | 业务词典 |
| `/recipes` | 配方版本 |

### 6.2 解析详情 Tabs

```text
结果 | 审核 | 反馈 | 时间线 | 版本 | 原文预览
```

- 结果：类别折叠、字段状态、单元格“反馈此字段”。
- 审核：Finding 列表、严重度、证据、定位。
- 反馈：新建、状态筛选、根因、消息、验证结果。
- 时间线：阶段、耗时、状态、产物、模型摘要。
- 版本：历史、对比、查看旧结果。
- 预览：页图 + 版面定位。

### 6.3 组件

```text
components/result/ResultTable.tsx
components/result/ResultJson.tsx
components/review/ReviewFindings.tsx
components/feedback/FeedbackDialog.tsx
components/feedback/VerificationDialog.tsx
components/timeline/RunTimeline.tsx
components/version/VersionCompare.tsx
components/recipe/RecipeTraceCard.tsx
components/ui/...
```

### 6.4 数据流

- TanStack Query 管理服务端状态。
- SSE `/v1/runs/{id}/events`；失败回退 3s 轮询。
- 写操作 `Idempotency-Key`。
- `X-Operator` 从本地配置读取，默认 `local`。
- 错误统一 toast + 页面级错误态。

## 7. 验收标准

### 7.1 功能

- [x] 上传文档、查看列表、删除。
- [x] 创建/重新解析、查看进度。
- [x] 结果表格/JSON、类别折叠、字段反馈入口。
- [x] 审核 Finding 可见、证据可定位。
- [x] 反馈创建、处理、验证通过/拒绝。
- [x] 时间线可见阶段/耗时。
- [x] 版本历史/对比。
- [x] 原文预览、页图/版面。
- [x] 词典、运行、配方页面可用。
- [x] 无登录/租户/工作区入口。

### 7.2 质量

| 指标 | 结果 |
|---|---|
| 主链路 E2E | 通过（Playwright 3/3） |
| 反馈闭环 E2E | 通过（M6 后端 E2E + 前端验证弹窗手工验证） |
| 旧前端依赖 | 0（未 import `legacy/`） |
| 视觉一致性 | Tokens 与现有产品一致；浏览器验证通过；未建立截图基线 |
| 首屏加载 | 未测（无历史基线）；构建产物 gzip JS 147KB |
| 控制台错误 | 0（浏览器验证） |
| 无障碍基础 | focus ring、`role=tab`、`aria-modal`、Esc 关闭 |
| 大结果表 | 未压测 1000 行；当前记录量级流畅 |

### 7.3 文档

- [x] 前端 README。
- [x] 页面/路由说明。
- [x] 组件说明。
- [x] API 调用说明。
- [x] E2E 报告。

## 8. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K7.1 工程/主题就绪 | 2027-03-01 | 可启动 |
| K7.2 文档库/结果可用 | 2027-03-08 | 主链路 |
| K7.3 审核/反馈可用 | 2027-03-13 | 闭环 |
| K7.4 时间线/版本可用 | 2027-03-15 | 完整视图 |
| K7.5 E2E 通过 | 2027-03-20 | 报告 |
| K7.6 验收 | 2027-03-21 | 签字 |

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| API 变更 | 先冻结契约；类型生成；mock |
| 大结果表性能 | 虚拟化/分页；按需加载 |
| 反馈验证交互复杂 | 先只读 diff，再操作；复用结果表 |
| 视觉风格不一致 | 先定 Tokens；组件统一 |
| 范围蔓延 | 非目标清单；变更评审 |
| E2E 不稳定 | 隔离 DB；mock 模型；固定数据 |

## 10. 出口准则与回滚

**出口准则**

- 主链路 + 反馈闭环 E2E 通过。
- 无旧前端依赖。
- 业务/QA/PM 验收。

**回滚**

- 旧前端继续服务；新前端独立部署。
- 关闭新入口不影响后端。
- 无数据迁移依赖。

## 12. 实施记录（2026-11-12）

### 12.1 代码落点

| 模块 | 路径 |
|---|---|
| 应用/路由 | `web/src/App.tsx`、`web/src/router.tsx`、`web/src/main.tsx` |
| 页面 | `web/src/pages/`（Documents/Extraction/Viewer/Runs/Dictionary/Recipes） |
| 组件 | `web/src/components/`（ui/result/review/feedback/timeline/version/recipe/preview） |
| API 客户端 | `web/src/api/`（client/types/documents/runs/feedback/recipes/dictionary） |
| 样式 Tokens | `web/src/styles.css` |
| E2E | `web/tests/e2e/m7-core.spec.ts`、`web/playwright.config.ts` |
| 后端补口 | `services/orchestration/api.py`、`services/orchestration/dictionary/`、`services/api_gateway/main.py` |

### 12.2 后端补口

- `GET /v1/runs/{id}/records`、`/review`、`/ocr`、`/pages/{page}/image`（页图缺失返回 404，前端回退 OCR 文本）。
- `GET /v1/dictionary`：只读查询旧词典快照（`services/orchestration/data/dictionary/business_dictionary.json`，95 条）；M8 负责正式导入/对账。
- `GET /v1/recipes`、`GET /v1/recipes/{id}`、`POST /v1/recipes/{id}/rollback`：网关代理 recipe-registry。

### 12.3 前端实现

- Tailwind 4 + Tokens（从旧产品 `globals.css` 提取）；侧边栏/顶栏/卡片/弹窗/表格统一组件。
- TanStack Query 管理服务端状态；运行中 1.5s 轮询；终态后加载结果/记录/审核。
- 详情页六 Tab；结果表按表分组折叠、字段反馈入口自动预填；验证弹窗展示 diff 与回归并支持通过/拒绝。
- 版本对比按 `record_id + measure`；预览页支持页图与 OCR 文本回退。

### 12.4 验证

- `npm run typecheck` / `npm run build`：通过（gzip JS 147KB，CSS 7.4KB）。
- Playwright：`web/tests/e2e/m7-core.spec.ts` 3/3 通过（文档库、详情六 Tab、运行/词典/配方）。
- 浏览器验证：反馈 Tab 与验证弹窗、时间线、版本差异、发起解析状态更新均通过；控制台无错误。
- 运行方式：Compose 栈 + `npm run dev`；如本机 Playwright 浏览器版本不匹配，可设置 `PLAYWRIGHT_CHROME_PATH` 复用已有 Chromium。

### 12.5 偏差与限制

- E2E 路径由计划的 `new_app/tests/e2e/` 调整为 `web/tests/e2e/`（Node 模块解析需在 web 包内）。
- 生产静态托管/Ingress 随 M8 切换；当前使用 Vite dev/preview。
- 词典为只读快照；编辑、导入、对账在 M8。
- 未建立自动视觉回归基线；大结果表 1000 行未压测。

## 13. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M6](M6-feedback-repair-promotion.md)
- 下一里程碑：[M8 词典导入、效果对比与切换](M8-dictionary-comparison-cutover.md)
- 前端说明：[web/README.md](../web/README.md)
- 视觉/交互：[M7-ui.md](reports/M7-ui.md)

## 14. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q5 视觉沿用现有风格、Q8 单人角色 | 项目负责人 |
| v1.2 | 2026-11-12 | 主体完成：六页面、六 Tab、后端补口、Playwright 3/3；补实施记录 | 项目负责人 |
