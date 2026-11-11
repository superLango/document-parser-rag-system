# 一站式解析对接接口（hansonDoc_RAG 兼容）

> 版本：v1（兼容 hansonDoc_RAG `docs/INTEGRATION_API.md`，源码 commit `c74ea91`）
> 日期：2026-11-10
> 适用：外部系统上传 PDF → OCR/解析 → 结构化抽取 → 状态/结果/页面查看

## 1. 兼容范围

本次把 hansonDoc_RAG 的「一站式解析」对接层原样接入当前平台：

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| POST | `/api/v1/integration/upload` | 一站式上传（PDF + `kb_id` + `prompt_id`） | 需要 |
| GET | `/api/v1/integration/tasks/{task_id}/status` | OCR + 抽取双阶段状态 | 不需要 |
| GET | `/api/v1/integration/tasks/{task_id}/result` | 结构化抽取结果 JSON | 不需要 |
| POST | `/api/v1/integration/tasks/{task_id}/retrigger` | 整流程重新触发 | 需要 |
| GET | `/api/v1/integration/tasks/{task_id}/session-token` | 签发只读结果页令牌 | 不需要 |
| GET（页面） | `/integration/task/{task_id}` | 结果查看页面 | 页面内按登录态处理 |

- 方法、路径、查询参数、表单字段、响应信封与旧系统一致。
- 服务直连地址：`http://<platform-host>:8000/api/v1/integration/...`
- 经 Web 代理访问：`http://<web-host>:8080/api/v1/integration/...`（nginx 已增加代理）
- 页面地址：`http://<web-host>:8080/integration/task/{task_id}`

所有接口返回旧统一信封：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "trace_id": "请求ID"
}
```

`code=0` 表示成功；非 0 为错误码：

| HTTP | code | 含义 |
|---|---|---|
| 400 | 10001 | 参数/文件校验失败 |
| 401 | 20001 | 未登录或 API Key 无效 |
| 403 | 20003 | 无权限 |
| 404 | 30017 | 对接任务不存在 |
| 409 | 30019 | 状态冲突（如正在解析时强制重触发） |
| 413 | 10001 | 文件超过大小限制 |
| 500 | 50000 | 服务内部错误 |

## 2. 认证与安全差异

旧系统对接接口完全无认证，并在内部使用超管会话绕过 RLS（审计项 A1/A2）。当前平台按配置切换：

- **免登录模式（`HANSON_REQUIRE_AUTH=false`，默认）**：
  - 所有接口（含 `upload`、`retrigger`、管理类接口）**不做任何鉴权/授权**；
  - 请求统一映射为内嵌访客 `embed_guest`，拥有全部工作空间/知识库的 owner 权限；
  - `Authorization`、`X-API-Key` 即使携带也**不会校验**，无效凭证不会返回 401；
  - 便于外部系统与旧系统零改造切换。
- **严格模式（`HANSON_REQUIRE_AUTH=true`）**：
  - **写接口**（`upload`、`retrigger`）必须携带以下任一凭证：
    - `Authorization: Bearer <access_token>`（平台登录令牌）；
    - `X-API-Key: <key>`（推荐外部系统使用，需具备 `documents:write` scope 且允许访问目标知识库）。
  - **读接口**（`status`、`result`、`session-token`）不需要登录；`task_id` 本身作为不可猜测的 128 位访问凭证。请勿把 `task_id` 暴露到公开日志或前端 URL 之外。
- `session-token` 返回的是 **15 分钟 HMAC 只读分享令牌**，不是旧系统的 2 小时超级管理员 JWT；页面用它打开 `/share/{token}` 只读结果，不再获得管理员身份。
- 页面 `/integration/task/{task_id}`：
  - 已登录/嵌入访客：内嵌当前平台的结构化抽取详情页，可复核、反馈、导出；
  - 严格模式且未登录：任务完成后自动跳转 `/share/{token}` 只读结果页；
  - 「重新触发」在免登录模式下可直接使用，严格模式下需登录。

### 2.1 嵌入模式配置（免登录）

外部系统嵌入本系统时，可通过配置文件/环境变量控制是否要求登录，默认**不要求登录**：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `HANSON_REQUIRE_AUTH` | `false` | `false`：无令牌请求自动使用固定访客身份 `embed_guest`；`true`：恢复强制登录/API Key |
| `HANSON_ANONYMOUS_USERNAME` | `embed_guest` | 免登录模式使用的用户，首次访问自动创建（角色 editor） |
| `HANSON_ALLOW_EMBED` | `true` | 允许被其他系统 iframe 嵌入（后端关闭 `X-Frame-Options`，CSP 使用 `frame-ancestors *`；nginx 静态头默认允许，需禁用时同时修改 `infra/docker/nginx.conf`） |

对应配置位置：

- Docker：`infra/docker/.env` 或 `infra/docker/compose.yaml` 的 `platform-api.environment`；
- 本地：启动 API 前设置同名环境变量。

行为说明：

- 免登录模式下，浏览器无痕窗口不会带 `localStorage` 登录令牌，但仍可正常访问：后端把所有请求（无论是否携带凭证）统一映射到 `embed_guest`，前端 `/v1/auth/config` 返回 `require_auth=false` 后不再跳转登录页。
- 免登录访客拥有所有工作空间/知识库的 owner 权限，外部系统上传到任意知识库的文档都可直接打开、复核、反馈、导出和重新触发。
- 免登录模式下登录令牌与 API Key 均被忽略；需要按用户/密钥做权限隔离时，必须切换到严格模式。
- 免登录 + 允许嵌入会把系统开放给能访问该地址的人，建议仅部署在内网或受网关保护的环境；需要鉴权时设置 `HANSON_REQUIRE_AUTH=true`、`HANSON_ALLOW_EMBED=false` 恢复严格模式。

## 3. 接口详情

### 3.1 一站式上传

**POST `/api/v1/integration/upload`**（multipart/form-data）

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `file` | form | file | 是 | PDF 文件，最大 50MB（以平台配置为准） |
| `kb_id` | query | string(UUID) | 是 | 当前平台知识库 ID，支持带 `-` 或不带 `-` |
| `prompt_id` | query | string(UUID) | 是 | 旧系统 Prompt ID；当前仅作为外部引用保存 |

```bash
curl -X POST "http://<host>:8000/api/v1/integration/upload?kb_id=<kb_id>&prompt_id=<prompt_id>" \
  -H "X-API-Key: <key>" \
  -F "file=@document.pdf"
```

响应 `data`（与旧系统一致）：

```json
{
  "task_id": "4e7a864c-4904-45b7-b424-2f95e2a6fdde",
  "kb_id": "25e7d8ef-6268-42d7-ba0c-62516ffc93f9",
  "document_id": "9a58c351-...",
  "prompt_id": "326d7916-7a5f-48cb-93f6-669b69744b7d",
  "schema_template_id": "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
  "filename": "GB-T1220-2007 不锈钢棒.pdf",
  "ocr_status": "processing",
  "ocr_progress": 0,
  "extract_status": "pending",
  "extract_progress": 0,
  "error": "",
  "result_version": null,
  "created_at": "2026-08-23T04:05:50.591391",
  "updated_at": "2026-08-23T04:05:50.591391"
}
```

说明：

- `task_id` 为 UUID；`kb_id`/`document_id` 返回带 `-` 的 UUID 形态，便于旧系统存储。
- 相同文件重复上传时，平台会复用同知识库下相同 SHA256 的文档，但每次上传都会创建新的 `task_id`。
- `prompt_id` 目前不参与模板选择：当前平台固定使用 `configs/schema_templates/product_standard.json`，其 `template_id` 即响应中的 `schema_template_id`。

### 3.2 状态查询

**GET `/api/v1/integration/tasks/{task_id}/status`**

```bash
curl "http://<host>:8000/api/v1/integration/tasks/<task_id>/status"
```

`data` 字段：

| 字段 | 说明 |
|---|---|
| `task_id` | 对接任务 ID |
| `kb_id` / `document_id` | 关联知识库/文档 |
| `filename` | 文件名 |
| `ocr_status` | `pending` / `processing` / `completed` / `failed` |
| `ocr_progress` | OCR 进度 0~100 |
| `extract_status` | `pending` / `queued` / `running` / `completed` / `failed` |
| `extract_progress` | 抽取进度 0~100 |
| `error` | 失败原因，成功为空字符串 |
| `result_version` | 结果版本，完成后有值 |
| `created_at` / `updated_at` | 任务时间 |

状态机：

```text
ocr:     pending → processing → completed
                                  ↘ failed
extract: pending → queued → running → completed
                                      ↘ failed
```

判断完成：`ocr_status=completed` 且 `extract_status=completed`。
判断失败：任一状态为 `failed`，此时读取 `error`。

### 3.3 抽取结果

**GET `/api/v1/integration/tasks/{task_id}/result`**

任务未完成或尚无结果时 `data` 为 `null`；失败时返回 `status=failed` 与 `error`；完成后返回：

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
        {"项目名称": "C", "材料牌号": "06Cr19Ni10", "标准要求": "0.04~0.10", "单位": "%"}
      ],
      "rejected": [],
      "missing_fields": [],
      "hit_count": 1
    }
  ],
  "summary": {"total_records": 60, "kept_categories": 8},
  "timing": {"total_sec": 312.45},
  "version": 3,
  "error": null,
  "updated_at": "2026-08-23T04:35:00"
}
```

- `categories[].records` 为当前平台 hansonDoc Schema 行，字段名与旧系统一致（项目名称/材料牌号/标准要求/单位/位置等）。
- `summary.total_records` 为所有类别记录数之和；`kept_categories` 为有记录的类别数。
- `timing.total_sec` 来自引擎 `trace.json` 的 `elapsed_ms`。

### 3.4 整流程重新触发

**POST `/api/v1/integration/tasks/{task_id}/retrigger`**（需要鉴权）

重新执行 OCR → 表格/条款抽取 → Schema 投影，复用原 `task_id`，返回与上传相同的任务视图。若任务正在解析，返回 409（code 30019）。

```bash
curl -X POST "http://<host>:8000/api/v1/integration/tasks/<task_id>/retrigger" \
  -H "X-API-Key: <key>"
```

### 3.5 会话令牌

**GET `/api/v1/integration/tasks/{task_id}/session-token`**

```json
{
  "task_id": "4e7a864c-...",
  "token": "<15分钟HMAC分享令牌>",
  "document_id": "9a58c351-...",
  "kb_id": "25e7d8ef-...",
  "expires_at": "2026-08-23T04:50:00",
  "path": "/share/<token>"
}
```

旧系统该接口签发 2 小时超级管理员 JWT；当前改为只读分享令牌，只能查看该文档结果，不能编辑或调用写接口。

## 4. 结果页面

**GET `/integration/task/{task_id}`**

```text
http://<host>:8080/integration/task/<task_id>
```

页面内容：

- 顶部：文件名、`task_id`、返回、问题反馈、导出、重新触发（需登录）；
- 状态条：OCR 解析/结构化抽取状态与进度、结果版本、更新时间、失败原因；
- 完成后：
  - 已登录/嵌入访客：内嵌当前平台结构化抽取详情页（复核、问题反馈、历史、跨标准补全、导出等）；
  - 未登录严格模式：跳转 `/share/<token>` 只读结果页；
- 页面顶部的「导出」使用 `session-token` 签发的只读分享令牌调用
  `/v1/share/{token}/export?format=hanson|json|csv|xlsx`，登录与否均可用，
  导出格式与结构化抽取内页一致；
- 「问题反馈」与结构化抽取内页共用同一套反馈/自愈流程：已登录或嵌入访客
  直接打开反馈弹窗，未登录严格模式下提示先登录。

## 5. 与旧系统的差异清单

| 项 | 旧系统 | 当前平台 | 影响 |
|---|---|---|---|
| 写接口认证 | 无 | 免登录模式：无；严格模式：JWT 或 `X-API-Key` | 默认免登录，零改造切换 |
| 页面免登录 | 自动签发管理员 JWT | 免登录模式直接使用访客；严格模式用 15 分钟只读分享令牌 | 严格模式未登录只能查看 |
| `prompt_id` | 绑定 Schema 模板 | 仅保存外部引用，固定产品标准模板 | 不按 prompt 切换 schema |
| ID 形态 | 全 UUID | `task_id` UUID；`kb_id`/`document_id` 响应为 UUID，内部 32 位 | 兼容旧存储 |
| 错误体 | `{code,message,data,trace_id}` | 同左 | 无变化 |
| 终态回调 | 主动 POST `receiveParseStatus` | 暂未迁移，请轮询 status | 若必须回调需后续增量实现 |
| OCR/索引 | OCR → 向量索引 → 抽取 | OCR → 表格/条款抽取 → Schema 投影 | 当前产品不做向量索引 |

## 6. 接入准备

1. 在平台创建知识库，取得 `kb_id`。
2. 创建 API Key（建议限定工作空间/知识库白名单，scope 至少 `documents:write`）：

```bash
curl -X POST "http://<host>:8000/v1/api-keys" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"one-stop-integration","scopes":"documents:read,documents:write","workspace_id":"<workspace_id>","kb_ids":"<kb_id>"}'
```

3. 用返回的明文 Key 调用 `/api/v1/integration/upload`。
4. 轮询 `status` 至 `ocr_status=completed` 且 `extract_status=completed`。
5. 调用 `result` 取结构化结果，或把 `task_id` 拼到 `/integration/task/{task_id}` 打开页面。

## 7. 本地验证（不启动模型）

```powershell
cd f:\hanson\hanson_doc_parse\apps\api
python -m unittest tests.test_integration_api -v
```

测试使用 mock OCR/抽取器，覆盖：

- 上传路径/参数/信封、UUID 兼容、PDF 校验、鉴权失败；
- 状态查询与完成态映射；
- 结果 JSON 形状与模板信息（字段集合与旧契约逐项对齐）；
- `categories` 每项固定含 `feature/records/rejected/missing_fields/hit_count`；
- session-token、只读分享结果与导出下载；
- 重触发鉴权、复用原 `task_id`；
- 404/400 错误信封与旧错误码（30017/10001/20001）；
- 免登录模式（`require_auth=false`）：无效 Bearer/API Key 不返回 401，
  工作空间、知识库、用户、API Key、上传与重触发均直接放行。

前端对接页测试（问题反馈入口、导出弹窗、内嵌抽取页）：

```powershell
cd f:\hanson\hanson_doc_parse\apps\web
npm test
```
