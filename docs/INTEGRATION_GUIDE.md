# 系统对接接口文档（公开一体化抽取）

> 本文档面向**外部系统集成方**，描述如何通过 HansonDOC RAG 提供的免鉴权一体化接口，实现「上传 PDF → 自动 OCR + 结构化抽取 → 获取结果」的端到端文档处理能力。

---

## 目录

1. [概述](#1-概述)
2. [接入准备](#2-接入准备)
3. [鉴权与安全](#3-鉴权与安全)
4. [通用约定](#4-通用约定)
5. [处理流程与状态机](#5-处理流程与状态机)
6. [接口详解](#6-接口详解)
   - [6.1 上传文档](#61-上传文档)
   - [6.2 查询处理状态](#62-查询处理状态)
   - [6.3 获取抽取结果](#63-获取抽取结果)
   - [6.4 预览源文件](#64-预览源文件)
7. [错误码对照表](#7-错误码对照表)
8. [集成示例](#8-集成示例)
9. [轮询策略建议](#9-轮询策略建议)
10. [嵌入预览页面](#10-嵌入预览页面)
11. [限制与注意事项](#11-限制与注意事项)

---

## 1. 概述

HansonDOC RAG 提供一组**免鉴权**的公开接口，外部系统无需登录即可调用。上传 PDF 文件后，系统在后台自动完成：

```
上传 PDF → GLM-OCR 识别 → MinerU-Popo 版面重建 → 五维向量入库 → 结构化抽取 → 结果落库
```

调用方只需三步：

1. **上传**：`POST /public/extraction/upload` → 获得 `task_id`
2. **轮询**：`GET /public/extraction/{task_id}/status` → 等待处理完成
3. **取结果**：`GET /public/extraction/{task_id}/result` → 获取结构化抽取结果 JSON

另外提供 `GET /public/extraction/{task_id}/preview` 用于在浏览器中内联预览原始 PDF。

---

## 2. 接入准备

### 2.1 服务地址

| 环境 | Base URL |
|------|----------|
| 开发/内网 | `http://<服务器IP>:8000/api/v1` |

所有公开接口挂载在 `${BASE_URL}/public/extraction` 下。

### 2.2 知识库（KB）

抽取强依赖知识库配置（Schema 模板 / Prompt / 术语集 / LLM 端点），无法绕过。调用上传接口时通过 `kb_id` 指定目标知识库：

- **方式一（推荐）**：由系统管理员在服务端配置默认公共知识库（环境变量 `PUBLIC_KB_ID`），调用方不传 `kb_id` 即可使用。
- **方式二**：调用方在请求中显式传入 `kb_id`（需事先在平台创建并配置好该知识库）。

> **当前环境配置最全的知识库**：「航天航空检测标准抽取」，`kb_id = 47a6507d-0492-5b54-99f7-2523f7b93893`（已配置 1 个 Schema 模板 / 5 个类别 / 1 个 Prompt / 3 个术语集 / 抽取配置 / 6 个脚本），可直接用于对接测试。

> 若既未传 `kb_id`、服务端也未配置 `PUBLIC_KB_ID`，上传将返回错误。

### 2.3 支持的文件类型

| 扩展名 | 说明 |
|--------|------|
| `.pdf` | 主支持（推荐） |
| `.png` `.jpg` `.jpeg` `.tiff` `.tif` `.bmp` | 图片类型 |

单文件大小上限：**500 MB**（524,288,000 字节）。

---

## 3. 鉴权与安全

### 3.1 免鉴权

本组接口**无需任何 Token 或 API Key**，可直接调用。适合后端服务间集成与嵌入页面场景。

### 3.2 安全机制

由于免鉴权，系统采用以下缓解措施保障安全：

| 机制 | 说明 |
|------|------|
| 雪花 ID | `task_id` 使用雪花算法生成，非自增整数，**不可顺序枚举**，他人无法遍历他人任务 |
| IP 限流 | 上传 10 次/分钟，状态/结果查询 60 次/分钟，超限返回 `429` |
| 配置校验 | 上传时校验目标 KB 的抽取配置是否完备，配置缺失直接报错，不产生无效任务 |
| 数据隔离 | 文件存入 KB 专属 MinIO bucket，结果按 KB 隔离 |

> `task_id` 即为访问凭据，调用方需妥善保管，避免泄露导致结果被他人读取。

---

## 4. 通用约定

### 4.1 统一响应体

除「预览源文件」接口返回二进制流外，所有接口返回统一 JSON 结构：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... },
  "trace_id": "trace-1723..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | `0` 成功；非 `0` 业务错误 |
| `message` | string | 状态描述，成功为 `"success"` |
| `data` | object / null | 业务数据，失败时通常为 `null` |
| `trace_id` | string | 链路追踪 ID，排障时提供 |

### 4.2 时间格式

所有时间字段为 ISO 8601 UTC 字符串，如 `2026-08-08T08:00:00Z`。

### 4.3 字符编码

请求与响应统一 UTF-8 编码。

### 4.4 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| `200` | 成功（查询/结果/预览） |
| `201` | 创建成功（上传） |
| `400` | 业务错误（文件过大/类型不支持/任务不存在/配置缺失等） |
| `429` | 触发限流 |
| `500` | 服务内部错误 |

> 业务错误（400）时，响应体 `code` 为非 0 业务错误码，`message` 描述具体原因。

---

## 5. 处理流程与状态机

### 5.1 状态流转

```
        ┌─────────┐
  上传 → │ queued  │ （已入队，等待执行）
        └────┬────┘
             ▼
        ┌───────────────┐
        │ ocr_processing │ （OCR 解析 + 版面重建 + 向量入库）
        └───────┬───────┘
                ▼
        ┌──────────┐
        │ ocr_done │ （OCR 完成，等待抽取）
        └─────┬────┘
              ▼
        ┌────────────┐
        │ extracting │ （结构化抽取中）
        └─────┬──────┘
              ▼
        ┌───────────┐        ┌────────┐
        │ completed │   或   │ failed │
        └───────────┘        └────────┘
         （终态）              （终态）
```

### 5.2 状态说明

| process_status | 含义 | 是否终态 |
|----------------|------|----------|
| `queued` | 排队中，已入队等待 worker 执行 | 否 |
| `ocr_processing` | OCR 解析中（GLM-OCR + Popo 重建 + 向量入库） | 否 |
| `ocr_done` | OCR 完成，即将进入抽取阶段 | 否 |
| `extracting` | 结构化抽取中（多类别并发 LLM 抽取） | 否 |
| `completed` | 处理完成，可获取结果 | **是** |
| `failed` | 处理失败，`message` 含失败原因 | **是** |

> `is_terminal=true` 时应停止轮询。`completed` 调结果接口，`failed` 根据原因决定是否重试（需重新上传）。

### 5.3 典型耗时

| 阶段 | 参考耗时（PDF，几十页） |
|------|------------------------|
| OCR + 版面重建 + 向量入库 | 30 秒 ~ 2 分钟 |
| 结构化抽取 | 1 ~ 3 分钟（取决于类别数） |
| 全流程 | 通常 2 ~ 5 分钟 |

> 实际耗时受文档页数、类别数量、LLM 并发配置影响，建议轮询超时设为 **15 分钟**。

---

## 6. 接口详解

### 6.1 上传文档

上传 PDF 文件，自动触发后台一体化处理，立即返回 `task_id`。

```
POST /public/extraction/upload
```

**请求**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `file` | form-data | file | 是 | 待上传的文件（≤500MB，支持 pdf/png/jpg/jpeg/tiff/bmp） |
| `kb_id` | query | string | 否 | 知识库 ID，未传时用服务端默认公共 KB |

**Content-Type**：`multipart/form-data`

**成功响应**（HTTP 201）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "7850e52xxxxxxxxxxxxxx",
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "queued"
  },
  "trace_id": "trace-1723..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID（雪花 ID），**后续所有操作的凭据** |
| `document_id` | string | 文档 ID（UUID） |
| `status` | string | 固定为 `"queued"` |

**常见错误**

| 场景 | HTTP | code | message 示例 |
|------|------|------|-------------|
| 文件超过 500MB | 400 | 30004 | 文件大小 xxx 字节超过上限 xxx 字节 |
| 不支持的文件类型 | 400 | 30005 | 不支持的文件类型：.docx，允许：.pdf, .png, ... |
| 未指定 kb_id 且无默认 KB | 400 | 30003 | 未指定知识库（kb_id），且系统未配置默认公共知识库 |
| kb_id 格式非法 | 400 | 30003 | 知识库 ID 格式非法：xxx |
| KB 抽取配置不完备 | 400 | 30003 | （具体缺失项，如未配置 Schema/Prompt/术语集） |
| 任务队列不可用 | 400 | 30003 | 任务队列服务不可用，请稍后重试 |
| 触发限流 | 429 | - | - |

---

### 6.2 查询处理状态

凭 `task_id` 查询当前处理进度。

```
GET /public/extraction/{task_id}/status
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 上传时返回的任务 ID |

**成功响应**（HTTP 200）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "7850e52xxxxxxxxxxxxxx",
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "process_status": "extracting",
    "progress": 45,
    "message": "结构化抽取中",
    "filename": "LSAM-JD01-0016 优质GH4169合金锻制棒材.pdf",
    "is_terminal": false
  },
  "trace_id": "trace-1723..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `process_status` | string | 当前状态（见[状态机](#5-处理流程与状态机)） |
| `progress` | integer | 进度百分比 0-100（参考值，非线性） |
| `message` | string | 中文状态描述；失败时为具体失败原因 |
| `filename` | string | 原始文件名 |
| `is_terminal` | boolean | 是否终态（completed/failed），`true` 时停止轮询 |

**常见错误**

| 场景 | HTTP | code | message |
|------|------|------|---------|
| task_id 不存在 | 400 | 30003 | 任务不存在：xxx |
| 触发限流 | 429 | - | - |

---

### 6.3 获取抽取结果

任务完成后，获取结构化抽取结果 JSON。未完成时返回当前状态。

```
GET /public/extraction/{task_id}/result
```

**成功响应 — 已完成**（HTTP 200）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "completed",
    "task_id": "7850e52xxxxxxxxxxxxxx",
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "LSAM-JD01-0016 优质GH4169合金锻制棒材.pdf",
    "schema_name": "产品标准抽取模板",
    "extracted_at": "2026-08-08T08:30:00Z",
    "summary": { "total_records": 42, "categories": 6 },
    "timing": { "ocr_ms": 45230, "extraction_ms": 128000 },
    "result": {
      "categories": [
        {
          "feature": "高温光滑持久",
          "records": [
            { "试验温度": "650℃", "应力": "690MPa", "持续时间": "≥100h" }
          ]
        }
      ],
      "summary": { ... },
      "timing": { ... }
    }
  },
  "trace_id": "trace-1723..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"completed"` |
| `schema_name` | string / null | 使用的 Schema 模板名 |
| `extracted_at` | string / null | 抽取完成时间（ISO 8601） |
| `summary` | object / null | 抽取摘要（记录数/类别数等） |
| `timing` | object / null | 各阶段耗时统计 |
| `result` | object / null | 抽取结果主体 |
| `result.categories` | array | 按类别组织的记录列表 |
| `result.categories[].feature` | string | 类别名 |
| `result.categories[].records` | array | 该类别的记录列表（字段由 Schema 定义） |

**成功响应 — 未完成**（HTTP 200）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "extracting",
    "message": "结构化抽取中",
    "result": null
  },
  "trace_id": "trace-1723..."
}
```

> 未完成时 `result` 为 `null`，`status` 为当前 `process_status`。建议先轮询 status 接口至 `completed`，再调本接口。

**常见错误**

| 场景 | HTTP | code | message |
|------|------|------|---------|
| task_id 不存在 | 400 | 30003 | 任务不存在：xxx |

---

### 6.4 预览源文件

流式返回原始上传文件，浏览器内联显示（PDF 直接在浏览器中打开）。适合在嵌入页面的 iframe 中作为源文件查看器。

```
GET /public/extraction/{task_id}/preview
```

**响应**

- **Content-Type**：按文件扩展名映射（如 `application/pdf`）
- **Content-Disposition**：`inline; filename="原始文件名"; filename*=UTF-8''<url编码文件名>`
- **Cache-Control**：`private, max-age=3600`
- **Body**：文件二进制流

> 该接口**不走统一响应体**，直接返回二进制流。可直接作为 `<iframe src="...">` 或 `<img src="...">` 的 URL。

**常见错误**

| 场景 | HTTP | code | message |
|------|------|------|---------|
| task_id 不存在 | 400 | 30003 | 任务不存在：xxx |
| 文档未关联原始文件 | 400 | 30003 | 该文档未关联原始文件 |
| 文件读取失败 | 400 | 30003 | 文件读取失败 |

---

## 7. 错误码对照表

| code | 含义 | 触发场景 |
|------|------|----------|
| `0` | 成功 | 正常响应 |
| `30003` | 任务/业务失败 | 任务不存在、队列不可用、配置缺失、kb_id 非法、文件读取失败等 |
| `30004` | 文件过大 | 超过 500MB |
| `30005` | 不支持的文件类型 | 扩展名不在允许列表 |

> 限流（429）由网关层返回，无业务 code。服务内部错误（500）`code` 为 `50000` 段。

---

## 8. 集成示例

### 8.1 cURL

```bash
# 1. 上传
curl -X POST http://localhost:8000/api/v1/public/extraction/upload \
  -F "file=@/path/to/document.pdf" \
  -F "kb_id=47a6507d-0492-5b54-99f7-2523f7b93893"
# → {"code":0,"data":{"task_id":"7850...","document_id":"...","status":"queued"}}

# 2. 查询状态（用返回的 task_id）
curl http://localhost:8000/api/v1/public/extraction/7850.../status

# 3. 获取结果（status 为 completed 后）
curl http://localhost:8000/api/v1/public/extraction/7850.../result

# 4. 预览源文件（浏览器或下载）
curl http://localhost:8000/api/v1/public/extraction/7850.../preview -o source.pdf
```

### 8.2 Python

```python
import time
import requests

BASE = "http://localhost:8000/api/v1/public/extraction"

def extract_document(pdf_path: str, kb_id: str = None) -> dict:
    # 1. 上传
    with open(pdf_path, "rb") as f:
        params = {"kb_id": kb_id} if kb_id else {}
        resp = requests.post(f"{BASE}/upload", files={"file": f}, params=params, timeout=60)
    resp.raise_for_status()
    task_id = resp.json()["data"]["task_id"]

    # 2. 轮询状态
    while True:
        resp = requests.get(f"{BASE}/{task_id}/status", timeout=30)
        data = resp.json()["data"]
        print(f"[{data['progress']}%] {data['message']}")
        if data["is_terminal"]:
            break
        time.sleep(3)

    # 3. 获取结果
    if data["process_status"] != "completed":
        raise RuntimeError(f"处理失败: {data['message']}")
    resp = requests.get(f"{BASE}/{task_id}/result", timeout=30)
    return resp.json()["data"]["result"]
```

### 8.3 JavaScript（前端）

```javascript
const BASE = '/api/v1/public/extraction'

async function extractDocument(file, kbId = '47a6507d-0492-5b54-99f7-2523f7b93893') {
  // 1. 上传
  const form = new FormData()
  form.append('file', file)
  const params = kbId ? `?kb_id=${kbId}` : ''
  const uploadRes = await fetch(`${BASE}/upload${params}`, { method: 'POST', body: form })
  const { data: upload } = await uploadRes.json()
  const taskId = upload.task_id

  // 2. 轮询状态
  let status
  do {
    await new Promise(r => setTimeout(r, 3000))
    const res = await fetch(`${BASE}/${taskId}/status`)
    status = (await res.json()).data
    console.log(`[${status.progress}%] ${status.message}`)
  } while (!status.is_terminal)

  if (status.process_status !== 'completed') {
    throw new Error(`处理失败: ${status.message}`)
  }

  // 3. 获取结果
  const resultRes = await fetch(`${BASE}/${taskId}/result`)
  return (await resultRes.json()).data.result
}
```

---

## 9. 轮询策略建议

| 项目 | 建议值 | 说明 |
|------|--------|------|
| 轮询间隔 | 3 秒 | 平衡实时性与限流（60次/分钟） |
| 最大轮询时长 | 15 分钟 | 超时视为异常，可告警 |
| 终态判断 | `is_terminal == true` | 优于判断具体 status 值 |
| 限流处理 | 收到 429 后退避 | 指数退避，最大间隔 30 秒 |

**推荐流程**：

```
上传 → 每 3 秒查 status → is_terminal=true?
                          ├ 是 → completed? → 取 result
                          │      └ failed → 记录原因，结束
                          └ 否 → 继续轮询（超 15 分钟告警）
```

> 避免在未完成时频繁调用 result 接口，优先用 status 接口判断终态后再取结果。

---

## 10. 嵌入预览页面

系统提供开箱即用的**免登录嵌入预览页面**，适合在第三方系统的 iframe 中直接展示「源 PDF + 抽取结果」左右分栏视图。

### 10.1 访问地址

```
http://<服务器IP>:5174/embed/extraction/{task_id}
```

将 `{task_id}` 替换为上传返回的任务 ID。

### 10.2 集成方式

```html
<iframe
  src="http://192.168.1.28:5174/embed/extraction/7850e52xxxxxxxxxxxxxx"
  style="width:100%; height:800px; border:0;"
></iframe>
```

### 10.3 页面特性

- **左侧**：源 PDF 内联预览（浏览器原生查看器）
- **右侧**：抽取结果摘要 + 类别列表（可展开查看记录表格 / JSON）
- **顶部**：文件名、任务 ID、状态徽标、显示/隐藏源文件开关
- 页面自动轮询任务状态，处理中显示进度，完成后展示结果
- `/embed/` 路径下的 401 错误静默处理，不跳转登录页

---

## 11. 限制与注意事项

| 项目 | 限制 |
|------|------|
| 单文件大小 | ≤ 500 MB |
| 文件类型 | pdf / png / jpg / jpeg / tiff / tif / bmp |
| 上传频率 | 10 次/分钟/IP |
| 查询频率 | 60 次/分钟/IP |
| 任务保留 | 任务记录与结果长期保留，可随时凭 task_id 查询 |
| 并发 | 单 KB 同时处理的任务数受 worker 并发配置限制，超出将排队 |
| task_id 安全 | task_id 即访问凭据，请妥善保管，避免泄露 |
| 结果字段 | `result.categories[].records` 的字段由 KB 的 Schema 模板定义，不同 KB 字段不同 |

### 注意事项

1. **KB 配置必须完备**：上传前确保目标 KB 已配置 Schema 模板、Prompt、术语集、LLM 端点，否则上传时即报错。
2. **失败处理**：`failed` 状态下 `message` 含失败原因。常见原因包括 OCR 失败、LLM 超时、模型服务不可用。需重新上传重试，不支持对同一任务恢复。
3. **task_id 唯一性**：雪花 ID 全局唯一，重复上传相同文件会生成不同 task_id，各自独立处理。
4. **时区**：所有时间字段为 UTC，展示时按需转换为本地时区。
5. **文件名编码**：preview 接口的 `Content-Disposition` 同时提供 ASCII `filename` 与 UTF-8 `filename*`，兼容各浏览器中文文件名。
