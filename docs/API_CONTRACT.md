# 接口契约文档

> 本文档定义 HansonDOC RAG 的统一 API 规范，作为前后端联调与第三方集成的契约基线。包含统一响应体、错误码、鉴权、限流规则与完整接口目录。

---

## 目录

1. [统一响应体](#1-统一响应体)
2. [错误码分段](#2-错误码分段)
3. [分页结构](#3-分页结构)
4. [时间格式](#4-时间格式)
5. [HTTP 状态码映射](#5-http-状态码映射)
6. [鉴权方式](#6-鉴权方式)
7. [限流](#7-限流)
8. [SSE 事件格式](#8-sse-事件格式)
9. [接口目录](#9-接口目录)
10. [公开一体化接口](#10-公开一体化接口)

---

## 1. 统一响应体

所有接口均返回统一的 JSON 响应体结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "trace_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 业务状态码，`0` 表示成功，非 `0` 表示业务错误 |
| `message` | string | 人类可读的状态描述，成功为 `"success"`，失败为错误描述 |
| `data` | object / null | 业务数据载荷，失败时可为 `null` |
| `trace_id` | string | 链路追踪 ID，用于全链路日志关联与排障 |

### 状态判定规则

- `code = 0`：业务成功
- `code ≠ 0`：业务错误，此时 `data` 通常为 `null`，`message` 描述错误原因

> 例外：文件下载、PDF 预览等二进制流接口直接返回 `StreamingResponse`，不包裹统一响应体。

---

## 2. 错误码分段

错误码采用 5 位整数分段设计，便于定位错误类别：

| 错误码段 | 类别 | 说明 | 示例 |
|----------|------|------|------|
| `1xxxx` | 参数校验 | 请求参数缺失、格式错误、类型不匹配 | `10001` 参数缺失 |
| `2xxxx` | 鉴权/权限 | 未登录、token 失效、无访问权限 | `20001` token 无效 |
| `3xxxx` | 业务逻辑 | 资源不存在、状态冲突、业务规则不满足 | `30001` 文档不存在 |
| `5xxxx` | 系统错误 | 服务内部异常、依赖故障、未知错误 | `50000` 内部错误 |

> HTTP 状态码与业务错误码独立。例如参数校验失败时 HTTP 状态码为 `400`，业务错误码为 `1xxxx`。

---

## 3. 分页结构

列表类接口的 `data` 字段统一采用如下分页结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "total": 100,
    "page": 1,
    "page_size": 20
  },
  "trace_id": "..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | array | 当前页数据条目列表 |
| `total` | integer | 符合条件的总记录数 |
| `page` | integer | 当前页码，从 `1` 开始 |
| `page_size` | integer | 每页条数 |

分页参数通过查询字符串 `page` 与 `page_size` 传入。

---

## 4. 时间格式

所有时间字段统一使用 **ISO 8601 UTC** 字符串，采用 `YYYY-MM-DDTHH:mm:ssZ` 格式：

```
2026-08-08T08:00:00Z
```

- 时区固定为 UTC，以 `Z` 结尾标识
- 前端展示时按需转换为本地时区

---

## 5. HTTP 状态码映射

| HTTP 状态码 | 含义 | 对应场景 |
|-------------|------|----------|
| `200` | 成功 | 业务处理成功 |
| `201` | 创建成功 | 资源创建（上传、新建） |
| `400` | 请求错误 | 参数校验失败（`1xxxx`） |
| `401` | 未授权 | 未携带 token 或 token 失效（`2xxxx`） |
| `403` | 禁止访问 | 无权限访问该资源（`2xxxx`） |
| `404` | 资源不存在 | 资源未找到（`3xxxx`） |
| `429` | 限流 | 超出限流阈值（`50001`） |
| `500` | 服务器内部错误 | 系统异常（`5xxxx`） |

---

## 6. 鉴权方式

采用 **Bearer Token** 鉴权，客户端在请求头携带：

```
Authorization: Bearer <access_token>
```

- `access_token` 由 `POST /api/v1/auth/login` 签发
- 支持 refresh token 静默续期（`POST /api/v1/auth/refresh`）
- token 失效返回 `401` 与业务错误码 `20001`
- 除公开接口（登录、健康检查、公开一体化抽取）外，所有接口均需鉴权

### 知识库隔离

知识库内接口（`/kbs/{kb_id}/*`）通过 `get_kb_context` 依赖激活 RLS 并校验成员资格与角色：

| 角色 | 权限 |
|------|------|
| owner | 知识库所有者，全部权限 |
| admin | 管理员，除删除 KB 外全部权限 |
| editor | 编辑者，上传/抽取/构建索引 |
| viewer | 查看者，只读 |

---

## 7. 限流

采用 slowapi 实施 IP 限流，命中限流时返回 HTTP `429`：

| 限流级别 | 阈值 | 适用接口 |
|----------|------|----------|
| 默认 | 60/min | 普通查询接口 |
| 上传 | 10/min | 文件上传接口 |
| AI | 较严格 | LLM 调用相关接口 |
| 公开上传 | 10/min | `POST /public/extraction/upload` |
| 公开查询 | 60/min | 公开状态/结果查询 |

---

## 8. SSE 事件格式

流式接口（如 RAG 流式回答）采用 **Server-Sent Events (SSE)** 协议：

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

事件数据格式（每条事件以两个换行符分隔）：

```
data: {"event":"token","content":"答"}\n\n
data: {"event":"token","content":"案"}\n\n
data: {"event":"done","result":{...}}\n\n
```

- 每个 `data:` 字段载荷为 JSON 字符串
- 事件之间以 `\n\n` 分隔
- 客户端使用 `EventSource` 或 fetch + ReadableStream 消费

---

## 9. 接口目录

所有接口挂载于 `/api/v1` 前缀下。下表按模块列出接口（同一路径的多个 HTTP 方法合并表示）。

### 9.1 认证与用户

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| auth | `/auth/login` | POST | 登录获取 token |
| auth | `/auth/refresh` | POST | 刷新 token |
| auth | `/auth/me` | GET | 当前用户信息 |
| auth | `/auth/profile` | PUT | 更新个人资料 |
| auth | `/auth/register` | POST | 注册 |
| auth | `/auth/change-password` | POST | 修改密码 |
| auth | `/auth/reset-password` | POST | 重置密码 |
| users | `/users` | GET/POST | 用户列表/创建 |
| users | `/users/{user_id}` | GET/PUT/DELETE | 用户详情/更新/删除 |
| users | `/users/{user_id}/active` | PATCH | 启用/禁用 |
| users | `/users/{user_id}/superuser` | PATCH | 超管切换 |
| users | `/users/{user_id}/reset-password` | POST | 管理员重置密码 |
| audit-logs | `/audit-logs` | GET | 审计日志列表 |
| audit-logs | `/audit-logs/actions` | GET | 操作类型 |
| audit-logs | `/audit-logs/stats` | GET | 统计 |

### 9.2 知识库管理

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kbs | `/kbs` | GET/POST | 知识库列表/创建 |
| kbs | `/kbs/{kb_id}` | GET/PUT/DELETE | 详情/更新/删除 |
| kbs | `/kbs/{kb_id}/active` | PATCH | 激活 |
| kbs | `/kbs/{kb_id}/stats` | GET | 统计 |
| kbs | `/kbs/{kb_id}/members` | GET/POST | 成员列表/添加 |
| kbs | `/kbs/{kb_id}/members/{user_id}` | PUT/DELETE | 成员角色/移除 |

### 9.3 知识库配置中心

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kb_config | `/kbs/templates` | GET | 领域模板列表 |
| kb_config | `/kbs/templates/{code}` | GET | 模板详情 |
| kb_config | `/kbs/{kb_id}/config` | GET/PUT | 全局配置读取/更新 |
| kb_config | `/kbs/{kb_id}/config/{section}` | GET/PUT | 分区配置 |
| kb_config | `/kbs/{kb_id}/apply-template` | POST | 应用领域模板 |
| kb_config | `/kbs/{kb_id}/hook` | GET/PUT/DELETE | Hook 脚本管理 |
| kb_config | `/kbs/{kb_id}/hook/content` | GET/PUT | Hook 内容 |
| kb_config | `/kbs/{kb_id}/hook/reload` | POST | 重载 Hook |
| kb_config | `/kbs/{kb_id}/domain/categories` | GET/POST | 领域类别 |
| kb_config | `/kbs/{kb_id}/domain/categories/{cat_id}` | PUT/DELETE | 类别更新/删除 |
| kb_config | `/kbs/{kb_id}/domain/regex-rules` | GET | 正则规则 |
| kb_config | `/kbs/{kb_id}/domain/field-templates` | GET | 字段模板 |
| kb_config | `/kbs/{kb_id}/config/validate` | POST | 配置校验 |
| kb_config | `/kbs/{kb_id}/resources/verify` | POST | 资源验证 |
| kb_config | `/kbs/{kb_id}/services` | GET | 外部服务配置 |
| kb_config | `/kbs/{kb_id}/services/status` | GET | 服务状态 |
| kb_config | `/kbs/{kb_id}/services/{service_name}` | GET/PUT | 服务配置 |
| kb_config | `/kbs/{kb_id}/services/{service_name}/validate` | POST | 服务验证 |
| kb_config | `/kbs/{kb_id}/diagnose` | POST | 诊断 |

### 9.4 抽取配置

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| extraction_config | `/kbs/{kb_id}/extraction-config` | GET | 配置总览 |
| extraction_config | `/kbs/{kb_id}/extraction-config/global` | GET/PUT | 全局抽取配置 |
| extraction_config | `/kbs/{kb_id}/extraction-config/prompts` | GET/POST | Prompt 模板列表/创建 |
| extraction_config | `/kbs/{kb_id}/extraction-config/prompts/{prompt_id}` | GET/PUT/DELETE | Prompt 详情/更新/删除 |
| extraction_config | `/kbs/{kb_id}/extraction-config/prompts/{prompt_id}/save` | POST | 保存 Prompt |
| extraction_config | `/kbs/{kb_id}/extraction-config/rules/registry` | GET | 规则注册表 |
| extraction_config | `/kbs/{kb_id}/extraction-config/rules` | GET/POST | 规则组列表/创建 |
| extraction_config | `/kbs/{kb_id}/extraction-config/scripts/io` | GET | 脚本 IO 描述 |
| extraction_config | `/kbs/{kb_id}/extraction-config/scripts` | GET/POST | 脚本列表/创建 |
| extraction_config | `/kbs/{kb_id}/extraction-config/scripts/{script_id}` | GET/PUT/DELETE | 脚本详情/更新/删除 |
| extraction_config | `/kbs/{kb_id}/extraction-config/scripts/run` | POST | 执行脚本 |
| extraction_config | `/kbs/{kb_id}/extraction-config/rule-groups` | GET/POST | 规则组 |
| extraction_config | `/kbs/{kb_id}/extraction-config/rule-groups/{group_id}` | GET/DELETE | 规则组详情/删除 |
| extraction_config | `/kbs/{kb_id}/extraction-config/rule-groups/{group_id}/items` | GET | 规则组项 |
| extraction_config | `/kbs/{kb_id}/extraction-config/validation` | GET/POST | 校验配置 |
| extraction_config | `/kbs/{kb_id}/extraction-config/bindings` | GET/POST | 绑定关系 |
| extraction_config | `/kbs/{kb_id}/extraction-config/versions` | GET/POST | 配置版本 |
| extraction_config | `/kbs/{kb_id}/extraction-config/versions/{version_id}` | GET/DELETE | 版本详情/删除 |
| extraction_config | `/kbs/{kb_id}/extraction-config/versions/{version_id}/rollback` | POST | 回滚版本 |
| extraction_config | `/kbs/{kb_id}/extraction-config/versions/{version_id}/diff` | GET | 版本差异 |

### 9.5 Schema 模板与术语

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| schema_templates | `/kbs/{kb_id}/schema-templates` | GET/POST | Schema 模板列表/创建 |
| schema_templates | `/kbs/{kb_id}/schema-templates/{template_id}` | GET/PUT/DELETE | 模板详情/更新/删除 |
| schema_templates | `/kbs/{kb_id}/schema-templates/{template_id}/categories` | GET/POST | 类别列表/创建 |
| schema_templates | `.../categories/{category_id}` | GET/PUT/DELETE | 类别详情/更新/删除 |
| schema_templates | `.../categories/{category_id}/fields` | GET/POST | 字段列表/创建 |
| schema_templates | `.../categories/{category_id}/fields/{field_id}` | GET/PUT/DELETE | 字段详情/更新/删除 |
| kb_term_bases | `/kbs/{kb_id}/term-bases` | GET/POST | 术语集列表/创建 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/{base_id}` | GET/PUT/DELETE | 术语集详情/更新/删除 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/test-api` | POST | 测试 API 连接 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/test-db` | POST | 测试 DB 连接 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/db-tables` | GET | 数据库表 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/preview-sql` | POST | 预览 SQL |
| kb_term_bases | `/kbs/{kb_id}/term-bases/{base_id}/terms` | GET | 术语集术语 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/{base_id}/terms/batch` | POST | 批量术语 |
| kb_term_bases | `/kbs/{kb_id}/term-bases/{base_id}/sync` | POST | 同步术语 |
| kb_terms | `/kbs/{kb_id}/terms/categories` | GET | 术语分类 |
| kb_terms | `/kbs/{kb_id}/terms/export` | GET | 导出术语 |
| kb_terms | `/kbs/{kb_id}/terms` | GET/POST | 术语列表/创建 |
| kb_terms | `/kbs/{kb_id}/terms/{term_id}` | GET/PUT/DELETE | 术语详情/更新/删除 |
| kb_terms | `/kbs/{kb_id}/terms/batch` | POST | 批量操作 |
| kb_terms | `/kbs/{kb_id}/terms/{term_id}/review` | POST | 审核 |

### 9.6 文档与任务

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kb_documents | `/kbs/{kb_id}/documents` | GET/POST | 文档列表/上传 |
| kb_documents | `/kbs/{kb_id}/documents/export` | GET | 导出文档列表 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}` | GET/DELETE | 文档详情/删除 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/download` | GET | 下载原文件 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/preview` | GET | 预览原文件（inline） |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/ocr-text` | GET | OCR 文本 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/extract` | POST | 触发结构化抽取 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/build-index-graph` | POST | 构建索引与图谱 |
| kb_documents | `/kbs/{kb_id}/documents/{document_id}/viewer-data` | GET | 查看器数据 |
| kb_documents | `/kbs/{kb_id}/documents/batch-delete` | POST | 批量删除 |
| kb_documents | `/kbs/{kb_id}/documents/batch-upload` | POST | 批量上传 |
| kb_tasks | `/kbs/{kb_id}/documents/{document_id}/parse` | POST | 触发 OCR 解析 |
| kb_tasks | `/kbs/{kb_id}/tasks` | GET | 任务列表 |
| kb_tasks | `/kbs/{kb_id}/tasks/stats` | GET | 任务统计 |
| kb_tasks | `/kbs/{kb_id}/tasks/{task_id}` | GET/DELETE | 任务详情/删除 |
| kb_tasks | `/kbs/{kb_id}/tasks/{task_id}/cancel` | POST | 取消任务 |
| kb_tasks | `/kbs/{kb_id}/tasks/{task_id}/retry` | POST | 重试任务 |
| kb_tasks | `/kbs/{kb_id}/batch-parse` | POST | 批量解析 |
| kb_tasks | `/kbs/{kb_id}/batch-retry` | POST | 批量重试 |
| tasks | `/tasks` | GET/POST | 全局任务列表/创建 |
| tasks | `/tasks/{task_id}` | GET | 任务详情 |
| tasks | `/tasks/{task_id}/retry` | POST | 重试 |
| tasks | `/tasks/v3-extract` | POST | v3 抽取任务 |
| tasks | `/tasks/{task_id}/stream` | GET | 任务流（SSE） |

### 9.7 抽取与搜索

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kb_extraction | `/kbs/{kb_id}/extraction/documents` | GET | 抽取文档列表 |
| kb_extraction | `/kbs/{kb_id}/extraction/schemas` | GET | 抽取 Schema |
| kb_extraction | `/kbs/{kb_id}/extraction/stream` | GET | 抽取流（SSE） |
| kb_extraction | `/kbs/{kb_id}/extraction/` | POST | 触发抽取 |
| kb_extraction | `/kbs/{kb_id}/extraction/results/{document_id}` | GET | 抽取结果 |
| kb_extraction | `/kbs/{kb_id}/extraction/history/{document_id}` | GET | 抽取历史 |
| kb_extraction | `/kbs/{kb_id}/extraction/export` | GET | 导出抽取结果 |
| kb_search | `/kbs/{kb_id}/search` | GET | 全文搜索 |

### 9.8 知识图谱与问答

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kb_graph | `/kbs/{kb_id}/graph` | GET | 图谱概览 |
| kb_graph | `/kbs/{kb_id}/graph/search` | GET | 实体搜索 |
| kb_graph | `/kbs/{kb_id}/graph/subgraph` | GET | 子图查询 |
| kb_graph | `/kbs/{kb_id}/graph/stats` | GET | 图谱统计 |
| kb_graph | `/kbs/{kb_id}/graph/documents/{document_id}` | GET/DELETE | 文档图谱 |
| kb_graph | `/kbs/{kb_id}/graph/rebuild` | POST | 重建图谱 |
| kb_qa | `/kbs/{kb_id}/qa/query` | POST | 问答（同步） |
| kb_qa | `/kbs/{kb_id}/qa/stream` | POST | 问答（SSE 流式） |
| kb_qa | `/kbs/{kb_id}/qa/health` | GET | 问答服务健康 |
| kb_qa_history | `/kbs/{kb_id}/qa/sessions` | GET/POST | 会话列表/创建 |
| kb_qa_history | `/kbs/{kb_id}/qa/sessions/{session_id}` | GET/DELETE | 会话详情/删除 |
| kb_qa_history | `/kbs/{kb_id}/qa/sessions/{session_id}/messages` | GET | 会话消息 |
| kb_qa_history | `/kbs/{kb_id}/qa/sessions/{session_id}/export` | GET | 导出会话 |

### 9.9 备份、通知、仪表盘、系统

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| kb_backup | `/kbs/{kb_id}/backups` | GET/POST | 备份列表/创建 |
| kb_backup | `/kbs/{kb_id}/backups/{backup_id}` | GET/DELETE | 备份详情/删除 |
| kb_backup | `/kbs/{kb_id}/backups/{backup_id}/download` | GET | 下载备份 |
| kb_backup | `/kbs/{kb_id}/backups/restore` | POST | 恢复备份 |
| notifications | `/notifications` | GET | 通知列表 |
| notifications | `/notifications/unread-count` | GET | 未读数 |
| notifications | `/notifications/subscribe` | GET | 订阅（SSE） |
| notifications | `/notifications/{notification_id}/read` | POST | 标记已读 |
| notifications | `/notifications/read-all` | POST | 全部已读 |
| notifications | `/notifications/{notification_id}` | DELETE | 删除通知 |
| notifications | `/notifications/read` | GET | 已读列表 |
| notifications | `/notifications/broadcast` | POST | 广播（管理端） |
| dashboard | `/dashboard/stats` | GET | 统计 |
| dashboard | `/dashboard/trends` | GET | 趋势 |
| dashboard | `/dashboard/distribution` | GET | 分布 |
| dashboard | `/dashboard/kbs/{kb_id}/stats` | GET | KB 统计 |
| system | `/system/health` | GET | 健康检查 |
| system | `/system/health/deep` | GET | 深度健康检查 |
| system | `/system/health/models` | GET | 模型健康 |
| system | `/system/health/storage` | GET | 存储健康 |
| system | `/system/info` | GET | 系统信息 |
| system | `/system/cleanup` | POST | 清理 |
| system | `/system/cleanup/dry-run` | POST | 清理预演 |
| system | `/system/check-ocr-layout` | GET | OCR 版面检查 |
| system | `/system/check-nebula-graph` | GET | Nebula 检查 |

---

## 10. 公开一体化接口

免鉴权的端到端文档处理通道，供外部系统集成。详细架构见 [ARCHITECTURE.md](ARCHITECTURE.md#41-一体化文档处理流程)。

### 10.1 上传 PDF

```
POST /api/v1/public/extraction/upload
```

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `file` | form | file | 是 | PDF 文件 |
| `kb_id` | query | string | 否 | 知识库 ID，未传用 `PUBLIC_KB_ID` |

**响应 data**：

```json
{
  "task_id": "雪花ID",
  "document_id": "UUID",
  "status": "queued"
}
```

### 10.2 查询处理状态

```
GET /api/v1/public/extraction/{task_id}/status
```

**响应 data**：

```json
{
  "task_id": "...",
  "document_id": "...",
  "process_status": "queued|ocr_processing|ocr_done|extracting|completed|failed",
  "progress": 0,
  "message": "中文状态描述",
  "filename": "原始文件名",
  "is_terminal": true
}
```

> `process_status` 独立于 `Task.status`，避免 OCR/抽取两阶段状态抖动。`is_terminal=true` 时停止轮询。

### 10.3 获取抽取结果

```
GET /api/v1/public/extraction/{task_id}/result
```

**响应 data**（completed 时）：

```json
{
  "status": "completed",
  "task_id": "...",
  "document_id": "...",
  "filename": "...",
  "schema_name": "Schema 模板名",
  "extracted_at": "ISO 8601 时间",
  "summary": {},
  "timing": {},
  "result": {
    "categories": [{"feature": "类别名", "records": [...]}],
    "summary": {},
    "timing": {}
  }
}
```

未完成时返回 `{status, message, result: null}`。

### 10.4 预览源文件

```
GET /api/v1/public/extraction/{task_id}/preview
```

返回 `StreamingResponse`，`Content-Disposition: inline`，浏览器内联显示 PDF，供嵌入预览页面左侧 PDF 查看器使用。
