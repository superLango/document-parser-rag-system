# 系统对接接口文档（一站式文档智能处理）

> 版本：v1 · 更新：2026-08-23
> 说明：当前对接接口**暂未启用认证**（先保证业务流程走通），后续接入认证时统一补充。

## 一、概述

系统对外提供「上传 → OCR 解析 → 结构化抽取」一站式处理能力，共四个交付物：

1. **一站式文档上传接口**：上传 PDF，指定知识库（`kb_id`）与 Prompt（`prompt_id`），返回 `task_id`，任务异步执行；
2. **状态查询接口**：通过 `task_id` 查询 OCR 与结构化抽取双阶段状态，失败返回原因；
3. **结果查看页面**：通过 URL 传入 `task_id` 打开抽取结果页（与系统内结构化抽取页一致，可重新抽取）；
4. **结果返回接口**：通过 `task_id` 返回结构化抽取结果 JSON。

### 整体流程

```
上传(POST /integration/upload)
  → 创建对接任务（task_id）+ 上传 PDF + 触发 OCR 解析
  → OCR 解析完成 + 向量索引完成
  → 自动触发结构化抽取（使用 prompt_id 绑定的 Schema 模板）
  → 抽取完成，可通过 task_id 查询状态 / 结果 / 打开结果页
```

全程通过 `task_id` 追踪，无需外部系统维护文档 id。

---

## 二、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/integration/upload` | 一站式上传（PDF + kb_id + prompt_id） |
| GET | `/api/v1/integration/tasks/{task_id}/status` | 任务状态（OCR + 抽取） |
| GET | `/api/v1/integration/tasks/{task_id}/result` | 抽取结果 JSON |
| POST | `/api/v1/integration/tasks/{task_id}/retrigger` | 整流程重新触发 |
| GET（前端） | `/integration/task/{task_id}` | 结果查看页面 |

所有接口返回统一结构：`{"code": 0, "message": "...", "data": ..., "trace_id": "..."}`；`code=0` 表示成功，非 0 为业务/系统错误。

---

## 三、接口详情

### 3.1 一站式上传

**POST `/api/v1/integration/upload`**（multipart/form-data）

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | PDF 文件（≤ 配置大小上限） |
| `kb_id` | string(UUID) | 是 | 知识库 ID |
| `prompt_id` | string(UUID) | 是 | Prompt 模板 ID（须绑定 Schema 模板且属于该知识库） |

**curl 示例**

```bash
curl -X POST "http://<host>:8000/api/v1/integration/upload?kb_id=<kb_id>&prompt_id=<prompt_id>" \
  -F "file=@document.pdf"
```

**响应示例**

```json
{
  "code": 0,
  "message": "任务已创建，正在异步执行 OCR 解析与结构化抽取",
  "data": {
    "task_id": "4e7a864c-4904-45b7-b424-2f95e2a6fdde",
    "kb_id": "25e7d8ef-...",
    "document_id": "9a58c351-...",
    "prompt_id": "326d7916-...",
    "schema_template_id": "6e2ad0d7-...",
    "filename": "GB-T1220-2007 不锈钢棒.pdf",
    "ocr_status": "processing",
    "ocr_progress": 0,
    "extract_status": "pending",
    "extract_progress": 0,
    "error": "",
    "result_version": null,
    "created_at": "2026-08-23T04:05:50.591391+00:00",
    "updated_at": null
  }
}
```

任务创建成功后即可用返回的 `task_id` 轮询状态。

---

### 3.2 状态查询

**GET `/api/v1/integration/tasks/{task_id}/status`**

**curl 示例**

```bash
curl "http://<host>:8000/api/v1/integration/tasks/{task_id}/status"
```

**响应 `data` 字段**

| 字段 | 说明 |
|---|---|
| `task_id` | 对接任务 ID |
| `document_id` | 关联文档 ID |
| `filename` | 文件名 |
| `ocr_status` | OCR 解析状态：`pending` / `processing` / `completed` / `failed` |
| `ocr_progress` | OCR 进度（0~100） |
| `extract_status` | 结构化抽取状态：`pending` / `queued` / `running` / `completed` / `failed` |
| `extract_progress` | 抽取进度（0~100） |
| `error` | 失败原因（成功为空字符串） |
| `result_version` | 抽取结果版本（完成后有值） |

**状态机**

```
ocr:   pending → processing → completed
                                 ↘ failed（返回 error）
extract: pending → queued → running → completed（result_version 有值）
                                     ↘ failed（返回 error）
```

**判断完成**：`ocr_status=completed` 且 `extract_status=completed`；
**判断失败**：`ocr_status=failed` 或 `extract_status=failed`，此时 `error` 字段包含失败原因。

---

### 3.3 抽取结果返回

**GET `/api/v1/integration/tasks/{task_id}/result`**

任务抽取完成后调用，返回结构化抽取结果 JSON（格式与系统内抽取结果一致）。

**响应 `data` 字段**

| 字段 | 说明 |
|---|---|
| `schema_template_id` / `schema_name` | 使用的 Schema 模板 |
| `status` | 结果状态（completed/failed） |
| `categories` | 抽取类别数组：`feature`、`records`（记录数组）、`rejected`、`missing_fields` 等 |
| `summary` | 汇总统计（总记录数、保留类别、跳过原因等） |
| `timing` | 耗时 |
| `version` | 结果版本 |
| `error` | 失败原因 |
| `updated_at` | 完成时间 |

**curl 示例**

```bash
curl "http://<host>:8000/api/v1/integration/tasks/{task_id}/result"
```

**响应示例（节选）**

```json
{
  "code": 0,
  "data": {
    "schema_template_id": "6e2ad0d7-...",
    "schema_name": "材料检测标准抽取",
    "status": "completed",
    "categories": [
      {
        "feature": "室温拉伸",
        "records": [
          { "材料牌号": "GH4169", "项目名称": "抗拉强度(Rm)", "标准要求": "≥1275", "单位": "MPa" }
        ],
        "rejected": [],
        "missing_fields": []
      }
    ],
    "summary": { "total_records": 60, "kept_categories": 8 },
    "version": 3,
    "updated_at": "2026-08-23T04:35:00+00:00"
  }
}
```

---

### 3.4 整流程重新触发

**POST `/api/v1/integration/tasks/{task_id}/retrigger`**

重新执行整个流程（重新 OCR 解析 → 索引 → 结构化抽取），复用原 `task_id`；返回与 3.1 相同的任务视图（状态被重置为 `processing/pending`）。

```bash
curl -X POST "http://<host>:8000/api/v1/integration/tasks/{task_id}/retrigger"
```

---

### 3.5 结果查看页面（前端）

浏览器访问（需登录系统）：

```
http://<host>:5174/integration/task/{task_id}
```

页面展示：

- 任务信息（文件名、task_id、OCR/抽取状态与进度、失败原因）；
- 抽取完成后内嵌系统结构化抽取结果页（与系统内页面完全一致，支持重新抽取、历史、CSV 导出等）；
- 「重新触发」按钮：整流程重跑。

---

## 四、注意事项

1. **认证**：当前对接接口未启用认证（无 token/API Key 校验），内部以超管上下文执行；正式对接前建议补充认证（如 API Key + 权限 scope）。
2. **文件格式**：仅支持 PDF。
3. **异步执行**：上传后任务在后台由 arq 异步执行，外部系统需轮询状态接口直至完成。
4. **依赖服务**：OCR 依赖 GLM-OCR 服务，抽取依赖 LLM 服务；两者未启动时任务会进入 `failed` 并在 `error` 返回具体原因（如 `LLM 请求失败：All connection attempts failed`）。
5. **抽取 Schema**：抽取仅使用 `prompt_id` 绑定的 Schema 模板类别，与系统内"按 KB 默认 Schema 抽取"相互独立。
6. **重新触发**：失败后可通过 `retrigger` 复用同一 `task_id` 重跑，无需重新上传。
