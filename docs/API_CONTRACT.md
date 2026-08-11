# API 契约

> 新后端保持与旧系统契约兼容，外部系统无需修改即可对接。

## 1. 统一响应体

```json
{ "code": 0, "message": "success", "data": {}, "trace_id": "550e8400-..." }
```

- `code = 0` 成功；非 0 为业务错误。
- 二进制流（下载/预览）直接返回 `StreamingResponse`，不包裹。

## 2. 错误码分段（5 位）

| 分段 | 类别 | 示例 |
|------|------|------|
| 1xxxx | 参数校验 | 10001 参数缺失 |
| 2xxxx | 鉴权/权限 | 20001 token 无效 |
| 3xxxx | 业务逻辑 | 30001 文档不存在 |
| 5xxxx | 系统错误 | 50000 内部错误 |

## 3. 分页

```json
{ "items": [], "total": 100, "page": 1, "page_size": 20 }
```

## 4. 时间与鉴权

- 时间：ISO 8601 UTC（`YYYY-MM-DDTHH:mm:ssZ`）。
- 鉴权：`Authorization: Bearer <access_token>`；refresh 静默续期。
- RBAC 角色：owner / admin / editor / viewer + `is_superuser`。

## 5. 限流

| 级别 | 阈值 |
|------|------|
| 默认 | 60/min |
| 上传 | 10/min |
| AI | 20/min |
| 公开上传/查询 | 10/min / 60/min |

## 6. SSE 事件格式

```
data: {"event":"token","content":"..."}\n\n
data: {"event":"done","result":{...}}\n\n
```

## 7. 公开一体化接口（保持不变）

- `POST /api/v1/public/extraction/upload`
- `GET /api/v1/public/extraction/{task_id}/status`
- `GET /api/v1/public/extraction/{task_id}/result`
- `GET /api/v1/public/extraction/{task_id}/preview`

`process_status` 状态机：`queued → ocr_processing → ocr_done → extracting → completed | failed`。

## 8. 路径收敛规则

- 业务资源一律 `GET/POST /api/v1/kbs/{kb_id}/...`。
- 全局旧路径（`/extraction`、`/tasks`、`/schemas`、`/terms`）随重构下线，
  迁移期内保留兼容映射并标记 `Deprecation` 头。

## 知识库文档接口（文档解析）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/kb/{kb_id}/documents` | editor+ | 上传 PDF（≤100MB）；创建“待解析”文档与任务，不自动解析 |
| POST | `/api/v1/kb/{kb_id}/documents/{doc_id}/start` | editor+ | 手动开始解析（幂等，复用上传创建的 queued 任务） |
| GET | `/api/v1/kb/{kb_id}/documents` | viewer+ | 文档列表（关键词分页） |
| GET | `/api/v1/kb/{kb_id}/documents/{doc_id}` | viewer+ | 文档详情/状态 |
| GET | `/api/v1/kb/{kb_id}/documents/{doc_id}/markdown` | viewer+ | result.md |
| GET | `/api/v1/kb/{kb_id}/documents/{doc_id}/layout` | viewer+ | layout.json（schema 1.2） |
| GET | `/api/v1/kb/{kb_id}/documents/{doc_id}/pages/{page}` | viewer+ | 单页 PNG |
| GET | `/api/v1/kb/{kb_id}/documents/{doc_id}/original` | viewer+ | 原始 PDF（待解析/解析中预览；对象缺失 400） |
| POST | `/api/v1/kb/{kb_id}/documents/{doc_id}/reparse` | editor+ | 重新解析（自动开始） |
| DELETE | `/api/v1/kb/{kb_id}/documents/{doc_id}` | editor+ | 删除文档与产物 |
| GET | `/api/v1/kb/{kb_id}/documents/tasks` | viewer+ | 任务列表（含 filename） |
