# 一站式解析对接文档

本文档描述旧系统 `hansonDoc_RAG` 一站式解析对接契约在当前平台上的落地方式。**接口路径、请求参数、响应结构和错误码保持与旧系统一致**，仅主机名和端口随部署环境变化。

## 1. 接入地址

| 方式 | Base URL | 说明 |
| --- | --- | --- |
| 网关直连 | `http://<host>:18000` | 推荐内部系统直连 |
| Web 反向代理 | `http://<host>:15173` | 与解析页面同源，nginx 已代理 `/api/` |

统一前缀：`/api/v1/integration`。

> 旧环境使用 `8000`（API）和 `8080`（Web）。当前部署这两个端口已被旧系统占用，因此新平台使用 `18000` / `15173`；**接口路径与调用方式完全不变**。

如部署时配置了 `API_AUTH_TOKEN`，请附加请求头：

```
Authorization: Bearer <token>
```

## 2. 统一响应结构

所有接口均返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "trace_id": "7f4c2d9e8a1b4c3d9e0f1a2b3c4d5e6f"
}
```

- `code = 0` 表示成功，非 0 表示业务错误。
- `trace_id` 优先透传请求头 `X-Request-ID`，未传时由服务生成。

## 3. 接口一：上传并创建解析任务

```
POST /api/v1/integration/upload
Content-Type: multipart/form-data
```

### 请求参数

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `kb_id` | UUID | 是 | 旧系统知识库 ID，当前平台仅落库留痕 |
| query | `prompt_id` | UUID | 是 | 旧系统提示词 ID，当前平台仅落库留痕 |
| form | `file` | file | 是 | PDF 文件，最大 50 MB |

### 示例

```bash
curl -X POST \
  "http://localhost:18000/api/v1/integration/upload?kb_id=11111111-1111-1111-1111-111111111111&prompt_id=22222222-2222-2222-2222-222222222222" \
  -F "file=@./GB_T_1591-2018.pdf;type=application/pdf"
```

### 响应 `data`

```json
{
  "task_id": "b980a4db-cb68-41f6-89ef-119199974983",
  "kb_id": "11111111-1111-1111-1111-111111111111",
  "document_id": "98b19b44-ef9d-4729-b62c-0562d9078842",
  "prompt_id": "22222222-2222-2222-2222-222222222222",
  "schema_template_id": "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
  "filename": "GB_T_1591-2018.pdf",
  "ocr_status": "pending",
  "ocr_progress": 0,
  "extract_status": "pending",
  "extract_progress": 0,
  "error": "",
  "result_version": 1,
  "created_at": "2026-11-15T10:20:30.123456+00:00",
  "updated_at": "2026-11-15T10:20:30.123456+00:00"
}
```

接口立即返回，OCR 与结构化解析异步执行。请使用 `task_id` 轮询状态。

## 4. 接口二：查询任务状态

```
GET /api/v1/integration/tasks/{task_id}/status
```

### 示例

```bash
curl "http://localhost:18000/api/v1/integration/tasks/b980a4db-cb68-41f6-89ef-119199974983/status"
```

### 状态取值

| 字段 | 取值 |
| --- | --- |
| `ocr_status` | `pending` / `processing` / `completed` / `failed` |
| `extract_status` | `pending` / `running` / `completed` / `failed` |

当前平台运行状态到旧契约的映射：

| 当前 run 状态 | `ocr_status` | `extract_status` |
| --- | --- | --- |
| `RECEIVED` | `pending` | `pending` |
| `OCR_RUNNING` | `processing` | `pending` |
| `OCR_DONE` | `completed` | `pending` |
| `ROUTING` / `ROUTED` | `completed` | `pending` |
| `SANDBOX_RUNNING` / `PARSED` / `REVIEWING` / `REPAIRING` / `REPARSING` | `completed` | `running` |
| `REVIEW_PASSED` / `HUMAN_REVIEW` / `HUMAN_APPROVED` / `STRUCTURED_READY` | `completed` | `completed` |
| `FAILED` / `UNROUTED` / `REVIEW_FAILED` / `HUMAN_REJECTED` / `CANCELLED` | `failed` 或 `completed` | `failed` |

`result_version` 从 1 开始，每次重新触发递增。

## 5. 接口三：获取结构化结果

```
GET /api/v1/integration/tasks/{task_id}/result
```

解析未完成时返回 `data = null`。完成后返回：

```json
{
  "schema_template_id": "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
  "schema_name": "产品标准抽取模板",
  "status": "completed",
  "progress": 100,
  "categories": [
    {
      "feature": "化学成分",
      "records": [
        {
          "项目名称": "C",
          "材料牌号": "Q355B",
          "标准要求": "≤0.20",
          "单位": "%",
          "试验方法": "GB/T 223",
          "试验温度": "",
          "位置": "",
          "方向": "",
          "尺寸厚度": "",
          "试样状态": "",
          "取样数量": "",
          "取样说明": "",
          "锻件类型": ""
        }
      ],
      "rejected": [],
      "missing_fields": [],
      "hit_count": 1
    }
  ],
  "summary": {
    "total_records": 2054,
    "kept_categories": 8
  },
  "timing": {
    "total_sec": 58.1
  },
  "version": 2,
  "error": null,
  "updated_at": "2026-11-15T10:21:28.000000+00:00"
}
```

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `categories[].feature` | 业务大类，如 化学成分 / 室温拉伸 / 冲击试验 / 热处理制度 |
| `categories[].records` | 该大类下的行，字段与旧契约一致 |
| `categories[].hit_count` | 行数 |
| `summary.total_records` | 全部大类行数之和 |
| `summary.kept_categories` | 非空大类数 |
| `timing.total_sec` | OCR + 结构化解析耗时（秒） |
| `version` | 结果版本号，与状态接口 `result_version` 一致 |

- 普通检测项目行字段：项目名称、材料牌号、标准要求、单位、试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型。
- 热处理制度行字段：工序名称、工艺名称、材料牌号、项目大类、保温温度、保温时间、升温速率、降温速率、装炉温度、出炉温度、冷却介质、介质温度。
- 标准信息会作为 `feature = "标准信息"` 的大类返回，行字段为 `标准名称`、`标准编号`。

## 6. 接口四：重新触发解析

```
POST /api/v1/integration/tasks/{task_id}/retrigger
```

```bash
curl -X POST \
  "http://localhost:18000/api/v1/integration/tasks/b980a4db-cb68-41f6-89ef-119199974983/retrigger"
```

- 成功返回新的任务视图，`result_version` 递增。
- 任务正在 OCR/结构化解析中时返回 `409`（`code = 30019`）。
- 已处于人工审核或完成状态的任务允许重新触发。

## 7. 兼容接口：会话令牌

```
GET /api/v1/integration/tasks/{task_id}/session-token
```

```json
{
  "task_id": "b980a4db-cb68-41f6-89ef-119199974983",
  "token": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
  "document_id": "98b19b44-ef9d-4729-b62c-0562d9078842",
  "kb_id": "11111111-1111-1111-1111-111111111111",
  "expires_at": "2026-11-15T11:20:30.123456+00:00",
  "path": "/integration/task/b980a4db-cb68-41f6-89ef-119199974983"
}
```

当前平台没有登录体系与分享鉴权，该接口仅保留旧契约字段供调用方兼容使用；页面本身通过不可猜测的 `task_id` 访问。

## 8. 独立解析页面

```
GET /integration/task/{task_id}
```

示例：`http://localhost:15173/integration/task/b980a4db-cb68-41f6-89ef-119199974983`

- 独立路由，不进入工作区布局，**没有左侧菜单、顶部导航和返回其他页面的入口**。
- 页面内容与当前“解析详情”一致：文档信息、解析状态、结果表格、跨标准、问题反馈、时间线、导出。
- 页面通过状态接口解析出 `document_id`，再复用现有解析详情组件。
- 任务不存在时展示错误提示，不提供任何跳转入口。

## 9. 错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | 10001 | 参数校验失败 / 非 PDF / 空文件 / 文件超限 |
| 401 | 20001 | 未认证（启用 API_AUTH_TOKEN 时） |
| 403 | 20003 | 无权限 |
| 404 | 30017 | 对接任务不存在 |
| 409 | 30019 | 任务正在解析中，不能重复触发 |
| 429 | 10017 | 触发过于频繁 |
| 500 / 502 / 503 | 50000 | 服务内部或上游不可用 |

错误响应示例：

```json
{
  "code": 30017,
  "message": "对接任务不存在",
  "data": null,
  "trace_id": "be08f2c3fb0f4bd9bbecb42848283af5"
}
```

## 10. 对接建议

1. 上传成功后保存 `task_id`，每 2–5 秒轮询 `/status`，直到 `extract_status` 为 `completed` 或 `failed`。
2. `completed` 后调用 `/result` 获取结构化数据；如需刷新结果，调用 `/retrigger` 并重新轮询。
3. `kb_id`、`prompt_id` 只做格式校验和留痕，当前平台不会用它们选择知识库或提示词。
4. 单文件限制 50 MB；nginx 层 `client_max_body_size` 为 120 MB。
