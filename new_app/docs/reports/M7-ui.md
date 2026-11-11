# M7 前端视觉与交互说明

> 日期：2026-11-12
> 范围：`new_app/web`（标准拆分核心页面）
> 视觉基线：现有产品风格（Q5），Tokens 提取自 `legacy/apps/web/src/styles/globals.css`

## 1. 视觉基线

| 项 | 取值 |
|---|---|
| 主色 | `#10b981`；深绿 `#059669`；hover `#047857` |
| 背景 | 页面 `#f7fcf9`，卡片 `#ffffff` |
| 文本 | 主 `#17221c`，次要 `#64748b` |
| 边框 | `#dfebe4`；聚焦环 `#34d399` |
| 圆角 | `0.625rem`（卡片 12px，弹窗 16px） |
| 阴影 | `--shadow-soft`（卡片）、`--shadow-lift`（悬浮）、`--shadow-modal`（弹窗） |
| 字体 | PingFang SC / 微软雅黑 / 系统字体；ID 与数值使用等宽 |
| 布局 | 侧边栏 240px + 顶栏 56px + 内容区 32px 内边距 |
| 动效 | fade-up 入场、pulse-dot 状态点；尊重 `prefers-reduced-motion` |

## 2. 页面

| 路由 | 页面 | 关键交互 |
|---|---|---|
| `/` | 文档库 | 上传（拖拽/选择）、列表、删除确认、发起解析、最近运行状态、运行中 1.5s 轮询 |
| `/documents/:id` | 解析详情 | 运行切换、六个 Tab、结果表/JSON 切换、字段反馈入口 |
| `/documents/:id/viewer` | 原文预览 | 页切换、页图或 OCR 文本回退、表格预览 |
| `/runs` | 运行记录 | 状态/关键字筛选、取消运行、跳转详情 |
| `/dictionary` | 业务词典 | 检测项目/试验方法/分类概览、关键词搜索、分类筛选 |
| `/recipes` | 配方版本 | 通道徽标、版本展开、回滚确认 |

## 3. 详情 Tabs

- **结果**：按 `table_id` 分组折叠；显示牌号、条件列、measure 值；单元格悬停出现反馈图标，点击切换到反馈 Tab 并预填字段。
- **审核**：审核摘要（错误/警告/提示/记录数）、Finding 卡片（严重度、来源、置信度、观测/期望、证据）。
- **反馈**：状态筛选、新建反馈、处理（Triage/Repair/沙箱验证）、验证弹窗（diff/回归/通过或拒绝）。
- **时间线**：运行概览、四阶段耗时、事件流与 payload。
- **版本**：基准/对比运行选择，按 `record_id + measure` 展示新增/消失/变化。
- **原文预览**：页图（无页图回退 OCR 文本）+ 表格前 5 行。

## 4. 数据与状态

- TanStack Query 查询键：`documents`、`runs`、`result`、`records`、`review`、`ocr`、`timeline`、`feedback`、`dictionary`、`recipes`。
- 运行中列表/时间线 1.5s 轮询；结果/审核/记录在运行终态后启用，避免 404 噪音。
- 写操作统一 `X-Operator: local` 与 `Idempotency-Key`。
- 页面级错误态 + 右下角 toast；弹窗支持 Esc 关闭与遮罩点击关闭。

## 5. 后端补口

为前端新增：

- `GET /v1/runs/{id}/records`、`/review`、`/ocr`、`/pages/{page}/image`
- `GET /v1/dictionary`（旧词典快照 95 条，M8 正式导入）
- `GET /v1/recipes`、`GET /v1/recipes/{id}`、`POST /v1/recipes/{id}/rollback`

## 6. 验证记录

- `npm run typecheck`：通过。
- `npm run build`：通过（CSS 35KB / JS 478KB，gzip 147KB）。
- 浏览器验证（Compose + Vite dev）：
  - 文档库：侧边栏、标题、上传按钮、文档表格均正常。
  - 解析详情：六个 Tab 存在；结果表 Q355B/Q235B，Z=22%/25%。
  - 反馈 Tab：新建反馈按钮、反馈卡片、验证弹窗与 diff 正常。
  - 时间线：阶段耗时与事件流正常；版本：差异表正常。
  - 词典：40 个检测项目、分类概览正常；配方：7 个配方、版本展开与回滚按钮正常。
  - 发起解析：后端 201，最近运行状态更新为“结构化就绪”。
- Playwright：`web/tests/e2e/m7-core.spec.ts` 3/3 通过（文档库、详情六 Tab、运行/词典/配方）。
  运行命令：`cd new_app/web && npm run test:e2e`；浏览器版本不匹配时可设置 `PLAYWRIGHT_CHROME_PATH` 复用本机 Chromium。

## 7. 已知限制

- 生产静态托管/Ingress 随 M8 切换；当前为 Vite dev/preview。
- 大结果表未启用虚拟滚动（1000 行以内）。
- 版本对比为记录级属性 diff，不做字段语义映射。
- 词典为只读快照，编辑/导入/对账在 M8。
