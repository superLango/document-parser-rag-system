# 结构化抽取 E1 · 数据与任务底座 报告

- 日期：2026-08-13
- 范围：016 迁移（结果/历史表 + documents.extraction_status + RLS）、模型、结果存储服务、抽取任务状态机（启动/执行/失败不重试）、sync 执行器分支。

## 交付内容

1. 迁移 [016_extraction_result.py](/home/grainuser/hansonDoc_RAG/backend/alembic/versions/016_extraction_result.py)：
   - `extraction_results`（每文档最新一条，kb_id+document_id 唯一）；
   - `extraction_history`（历史归档，保留 50 条）；
   - `documents.extraction_status`（nullable）；
   - 两表 RLS（SELECT=成员，写=owner/admin/editor，FORCE）。
   - 已应用开发库与测试库。
2. 模型：`ExtractionResult` / `ExtractionHistory` / `Document.extraction_status`。
3. 服务：
   - `services/extraction/result_store.py`：latest 读写、完成归档、历史裁剪 50、删除并重置文档状态；
   - `services/extraction/extraction_task_service.py`：启动校验（解析+索引 completed）、重复启动 409、状态机 running→completed/failed（失败不自动重试，写死信）；
   - `services/extraction/pipeline.py`：E1 占位（显式报错 E3 未实现，防止伪成功）；
   - `tasks/sync_executor.py`：新增 `document_extraction` 分支。
4. 任务：`DocumentTask.type / TaskOutbox.type` 支持 `document_extraction`。

## 测试覆盖率

| 层 | 用例数 | 覆盖内容 | 结果 |
|----|--------|----------|------|
| L1 单元 | 3 | 模型注册、历史上限常量、流水线占位报错 | ✅ |
| L2/L3 集成 | 5 | 启动建任务+outbox、前置校验、重复 409、同步失败状态机、结果归档/删除 | ✅ |
| L4 边界 | 2 | 历史 55→50 裁剪、删除重置文档状态 | ✅ |
| L5 安全 | 2 | RLS 策略 8 条、非超管角色跨 KB 隔离 | ✅ |

后端全量回归：**137/137 通过**（M34+M33+全局配置+E1）。

## 说明

- E1 不包含 HTTP 端点（E4）与前端页面（E5）；抽取启动服务已就绪，供 E4 端点直接调用。
- 抽取任务失败路径为终态（failed + 死信），无自动重试（B11 已确认）。
