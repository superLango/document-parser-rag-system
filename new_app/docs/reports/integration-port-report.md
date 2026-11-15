# 一站式解析接口移植测试报告

- 日期：2026-11-15
- 范围：旧项目 `legacy` 一站式解析的 4 个接口 + 1 个独立页面
- 结论：**通过**。接口路径、请求参数、响应结构、错误码与旧契约一致；页面独立运行，无侧边栏和跨页导航。

## 1. 移植内容

| 旧契约 | 当前实现 |
| --- | --- |
| `POST /api/v1/integration/upload` | 网关转发编排服务，创建 `integration_tasks` 与解析 run |
| `GET /api/v1/integration/tasks/{task_id}/status` | 将当前 run 状态机映射为 `ocr_status` / `extract_status` |
| `GET /api/v1/integration/tasks/{task_id}/result` | 从 `records` 产物投影为旧行结构 |
| `POST /api/v1/integration/tasks/{task_id}/retrigger` | 创建新 run，`result_version` 递增 |
| `GET /api/v1/integration/tasks/{task_id}/session-token` | 保留旧兼容字段（当前无登录体系） |
| `GET /integration/task/{task_id}` | 独立 React 路由，复用解析详情组件 |

### 关键实现点

- `kb_id`、`prompt_id` 保持 UUID 校验与响应返回，仅落库留痕；当前平台没有知识库/提示词概念。
- 上传按 SHA-256 复用已有文档，但每次上传都会创建独立 `task_id` 和解析 run。
- 重触发在任务处于 OCR/结构化解析中时返回 `409 / 30019`；人工审核态允许重触发。
- 结果行字段与旧契约对齐：项目名称、材料牌号、标准要求、单位、试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型；热处理使用独立列集合。
- 错误统一返回 `{code, message, data, trace_id}`，并在网关和编排服务两层都做了拦截，避免 FastAPI 默认 `422/detail` 泄漏到外部。
- nginx 新增 `/api/` 反代，vite 开发服务器同步新增 `/api` 代理。

## 2. 变更文件

| 文件 | 说明 |
| --- | --- |
| `services/orchestration/models.py` | 新增 `IntegrationTask` 模型 |
| `services/orchestration/migrations/versions/0012_integration_tasks.py` | 新建对接任务表与索引 |
| `services/orchestration/integration_api.py` | 四接口 + 会话令牌 + 状态/结果投影 |
| `services/orchestration/main.py` | 注册路由与对接错误处理 |
| `services/api_gateway/main.py` | `/api/v1/integration` 代理与错误处理 |
| `deploy/compose/nginx.conf` | `/api/` 反向代理 |
| `web/vite.config.ts` | 开发环境 `/api` 代理 |
| `web/src/api/integration.ts` | 对接接口客户端与类型 |
| `web/src/pages/IntegrationTaskPage.tsx` | 独立页面壳与任务状态解析 |
| `web/src/pages/ExtractionPage.tsx` | 支持外部传入 `documentId`，复用解析详情 |
| `web/src/router.tsx` | 新增 `/integration/task/:taskId` 顶层路由 |
| `tests/test_integration_contract.py` | 契约纯函数单测 |
| `docs/integration-api.md` | 对接文档 |

## 3. 测试结果

### 3.1 构建与静态检查

| 检查 | 结果 |
| --- | --- |
| `npm --prefix new_app/web run build` | 通过 |
| `ruff check`（编排、网关、新增测试） | 通过 |
| `pytest tests/test_integration_contract.py` | 4 passed |

单测覆盖：状态映射（RECEIVED / OCR_RUNNING / OCR_DONE / SANDBOX_RUNNING / HUMAN_REVIEW / FAILED）、普通行字段、热处理列、标准号与标准要求格式化。

### 3.2 接口端到端

测试样本：`gbt1591_2018.pdf`（约 1.1 MB）。测试结束后已删除，文档库恢复为 30 份。

| 用例 | 请求 | 结果 |
| --- | --- | --- |
| 上传 | `POST /upload` + 合法 `kb_id/prompt_id` | `code=0`，返回 `task_id`、`document_id`，状态 `pending` |
| 状态轮询 | `GET /status` | `pending → processing → completed`，`result_version=1` |
| 获取结果 | `GET /result` | `code=0`，`status=completed`，2054 行，8 个分类，`timing.total_sec=58.1` |
| 重新触发 | `POST /retrigger` | `code=0`，`result_version=2`，重新进入解析并完成 |
| 并发保护 | 解析中再次 `POST /retrigger` | HTTP `409`，`code=30019` |
| 会话令牌 | `GET /session-token` | `code=0`，返回 `token`、`expires_at`、`path` |
| 任务不存在 | `status` 使用随机 UUID | HTTP `404`，`code=30017` |
| 非法 task_id | `status` 使用 `not-a-uuid` | HTTP `400`，`code=10001` |
| 缺参数 | 上传不带 `kb_id/prompt_id` | HTTP `400`，`code=10001`，`message=参数校验失败` |
| 非 PDF | 上传 `package.json` | HTTP `400`，`code=10001`，`message=仅支持 PDF 文件` |
| 非法 UUID | `kb_id=x` | HTTP `400`，`code=10001` |
| 结果投影 | 抽样检查 | 标准信息、化学成分、室温拉伸、冲击试验、弯曲、外观质量、尺寸、超声波检验均正确分组 |

### 3.3 页面测试（Playwright）

访问 `http://localhost:15173/integration/task/{task_id}`，结果：

| 检查项 | 结果 |
| --- | --- |
| HTTP 状态 | 200 |
| 页面标题 | “一站式标准解析” |
| 左侧菜单 `<aside>` | 0 个 |
| 导航 `<nav>` | 0 个 |
| 页面链接 | 仅“新窗口打开”（PDF 预览），无文档库/问题台账/词典/配方/返回入口 |
| 结果表格 | 正常渲染，显示标准信息、化学成分、室温拉伸、冲击试验、弯曲、外观质量、尺寸、超声波检验 |
| 原文 PDF | iframe 可见，`/v1/documents/{id}/file` 返回 `200`、`application/pdf`、`%PDF-` 文件头；真实 Chrome 中正常渲染并显示页码 1/22 |
| 浏览器控制台错误 | 无 |
| 截图 | `docs/reports/integration-page.png`、`docs/reports/integration-page-complete.png` |

页面同时保留“确认结果”“重新解析”“导出”“问题反馈”“跨标准”“时间线”等解析页能力。

原文区复用解析详情页的 PDF 内嵌方式：`/v1/documents/{id}/file` 以 `inline` + `X-Frame-Options: SAMEORIGIN` 返回，左侧显示 PDF 阅读器，右上角“新窗口打开”可全屏查看。Playwright 默认无头 Chromium 不带 PDF 阅读器，会显示空白；使用本机 Chrome 验证时原文正常显示，这不是页面或接口问题。

### 3.4 文档库清理

- 删除首轮测试文档 `98b19b44-ef9d-4729-b62c-0562d9078842` 返回 `204`。
- 原文显示复测使用临时文档 `b3230cc0-82d3-4198-ac98-99fd225ed214`，复测后同样删除。
- 删除后 `GET /v1/documents` 数量为 **30**。
- 再次访问测试 `task_id` 返回 `404 / 30017`，确认 `integration_tasks` 随文档级联清理。

## 4. 兼容性说明

1. **主机与端口**：旧环境为 `8000` / `8080`，当前为 `18000` / `15173`，因为旧端口仍被旧系统占用。接口路径、参数和返回结构不变。
2. **kb_id / prompt_id**：只校验 UUID 并留痕，不参与解析路由；如后续接入知识库，可在 `IntegrationTask` 上扩展。
3. **session-token**：保留旧字段与路径，但当前页面不依赖令牌鉴权，任务本身通过不可猜测的 UUID 访问。
4. **标准信息**：优先使用标准索引；当索引标题仅剩年份时退回文件名解析，避免出现“标准名称为 2018”这类脏数据。
5. **结果分类**：按业务词典的项目大类投影；词典中的“外观质量”“尺寸”“超声波检验”等会排在已知检测大类之后。
6. **测试数据**：端到端测试任务与文档已删除，如需现场演示，请重新调用 `/upload` 创建任务。

## 5. 复现命令

```bash
# 构建并重启
wsl -e bash -lc "cd /mnt/f/hanson/hanson_doc_parse/new_app && docker compose -f deploy/compose/docker-compose.yml -p hanson-new-app build orchestration api-gateway web && docker compose -f deploy/compose/docker-compose.yml -p hanson-new-app up -d --no-deps orchestration api-gateway web"

# 单测
python -m pytest tests/test_integration_contract.py -q

# 上传
curl -X POST "http://localhost:18000/api/v1/integration/upload?kb_id=11111111-1111-1111-1111-111111111111&prompt_id=22222222-2222-2222-2222-222222222222" \
  -F "file=@./sample.pdf;type=application/pdf"

# 轮询与取结果
curl "http://localhost:18000/api/v1/integration/tasks/<task_id>/status"
curl "http://localhost:18000/api/v1/integration/tasks/<task_id>/result"
```
