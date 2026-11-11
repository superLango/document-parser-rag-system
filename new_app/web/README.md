# Hanson 标准拆分前端（new_app/web）

M7 重建的标准拆分核心工作台。视觉完全沿用现有产品（浅绿 + 白、系统中文字体、软阴影、侧边栏），不包含登录/用户/租户/工作区。

## 技术栈

- Vite 6 + React 19 + TypeScript（strict）
- Tailwind CSS 4（`@tailwindcss/vite`，Tokens 定义在 `src/styles.css`）
- TanStack Query 5（服务端状态）
- lucide-react 图标
- Playwright（E2E）

## 启动

```bash
cd new_app/web
npm install
npm run dev            # http://localhost:5173
```

Vite 代理：

- `/v1` → `http://localhost:18000`（api-gateway）
- `/internal` → `http://localhost:18001`（orchestration，调试用）

构建与检查：

```bash
npm run typecheck
npm run build
npm run test:e2e       # 需要 Compose 栈与 Chromium
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VITE_API_BASE` | `/v1` | API 前缀；跨域部署时可指向网关地址 |
| `API_BASE` | `http://localhost:18000` | E2E 直连网关 |
| `WEB_BASE_URL` | `http://127.0.0.1:5173` | E2E 页面地址 |

## 路由

| 路由 | 页面 |
|---|---|
| `/` | 文档库：上传、列表、删除、发起解析、最近运行 |
| `/documents/:id` | 解析详情：结果 / 审核 / 反馈 / 时间线 / 版本 / 原文预览 |
| `/documents/:id/viewer` | 原文预览：页图或 OCR 文本 + 表格 |
| `/runs` | 运行记录：状态、耗时、错误码、取消 |
| `/dictionary` | 业务词典：检测项目 / 试验方法 / 分类概览 |
| `/recipes` | 配方版本：通道、版本列表、回滚 |

## 数据流

- 所有服务端状态由 TanStack Query 管理，查询键见 `src/api/*.ts` 与页面。
- 运行未结束时，列表与时间线按 1.5s 轮询；详情查询在运行进入终态后启用。
- 写操作统一带 `X-Operator: local` 与 `Idempotency-Key`。
- 详情页通过 `?run=<id>` 固定当前运行，便于分享与版本对比。

## 组件

```text
components/
  ui/             Button / Badge / Card / Dialog / Tabs / Table / Toast / Form
  result/         ResultTable（按表分组、字段反馈入口）、ResultJson
  review/         ReviewFindings（严重度、证据、置信度）
  feedback/       FeedbackPanel、FeedbackDialog、VerificationDialog
  timeline/       RunTimeline（阶段耗时 + 事件流）
  version/        VersionCompare（record_id + measure 差异）
  recipe/         RecipeTraceCard（命中配方/模板/审核）
  preview/        PagePreview（页图或 OCR 文本 + 表格）
```

## API 依赖

除 M1/M5/M6 已有接口外，M7 新增/使用：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/v1/runs/{id}/records` | 结果表记录 |
| GET | `/v1/runs/{id}/review` | 审核报告与 Findings |
| GET | `/v1/runs/{id}/ocr` | 页面与表格（预览） |
| GET | `/v1/runs/{id}/pages/{page}/image` | 页图（无页图时 404，前端回退文本） |
| GET | `/v1/dictionary` | 业务词典只读查询 |
| GET | `/v1/recipes` | 配方与通道列表 |
| GET | `/v1/recipes/{id}` | 配方版本详情 |
| POST | `/v1/recipes/{id}/rollback` | 通道回滚 |

## 视觉基线

Tokens 从现有产品 `legacy/apps/web/src/styles/globals.css` 提取到 `src/styles.css`：

- 主色 `#10b981` / 深绿 `#059669`；背景 `#ffffff`、柔和底 `#f7fcf9`
- 字体：PingFang SC / 微软雅黑 / 系统字体；等宽用于 ID 与数值
- 圆角 `0.625rem`；软阴影 `--shadow-soft`、抬升 `--shadow-lift`
- 侧边栏 240px、浅绿渐变；顶栏 56px 半透明模糊
- 动效仅保留 fade-up 与 pulse-dot，支持 `prefers-reduced-motion`

## 已知限制

- 生产静态托管与 Ingress 接入随 M8 切换；当前用 Vite dev/preview。
- 大结果表暂未启用虚拟滚动；1000 行以内可用。
- 版本对比按 `record_id + measure` 比较，不做字段级语义 diff。
- 词典数据为旧词典快照（用于页面查询），正式导入/对账在 M8。
