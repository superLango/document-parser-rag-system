# 目标系统架构

## 1. 分层总览

```
┌──────────────────────────────────────────────────────────┐
│  React 前端（React 19 + TS + Tailwind 4 + Radix/shadcn）    │
│  auth / kb / documents / extraction / qa / graph / admin  │
└───────────────────────────┬──────────────────────────────┘
                            │ REST + SSE（统一响应体 + trace_id）
┌───────────────────────────▼──────────────────────────────┐
│  API 层（FastAPI）                                          │
│  路由 │ JWT 鉴权 │ RBAC │ 限流 │ 中间件 │ 统一异常          │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  服务层（Python 业务域）                                     │
│  ocr → popo → vector → extraction → term → graph → rag    │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  异步任务层（arq + Redis db1）                              │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  持久层（六层 KB 隔离）                                      │
│  PostgreSQL(RLS) │ MinIO(bucket) │ Milvus(Collection)     │
│  NebulaGraph(space) │ Redis(prefix+ACL) │ 配置三层覆盖     │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  AI 推理层（裸机 + GPU）                                    │
│  GLM-OCR(9977) │ Qwen(9988) │ Popo(9999) │ bge-m3         │
│  bge-reranker │ gliclass                                  │
└──────────────────────────────────────────────────────────┘
```

## 2. 模块边界约定

- `endpoints`（路由层）：只做参数校验、鉴权、调用 service、组装响应；禁止直连数据库与第三方。
- `services`（业务层）：承载全部业务逻辑；禁止 import FastAPI Request/Response。
- `models`（ORM 层）：只定义表结构与关系，不写业务。
- `schemas`（Pydantic 层）：请求/响应契约，不写业务。
- `tasks`（异步层）：只做任务编排与状态回写，业务委托 service。
- 前端 `features/` 页面只依赖 `api/` 与 `stores/`，不直接拼 URL。

## 3. 六层 KB 隔离（沿用）

| 层 | 实现 | 命名 |
|----|------|------|
| PostgreSQL | RLS：`SET LOCAL app.current_kb` | `kb_id` 列 |
| Milvus | 每 KB Collection | `doc_five_dim_{hex}`、`doc_chunks_{hex}` |
| MinIO/S3 | 每 KB bucket | `kb-{hex}` |
| NebulaGraph | 每 KB space | `kb_{hex}` |
| Redis | key 前缀 + ACL | `kb:{kb_id}:`（db0 缓存 / db1 队列） |
| 配置 | 全局 → KB config JSON → Hook | 三层覆盖 |

## 4. 核心链路（目标形态）

1. **文档处理**：上传 → MinIO → arq 编排 → GLM-OCR → Popo 重建 → 五维向量入库 →
   BM25 模型 → 结构化抽取 → 结果落库 → 公开接口轮询。
2. **RAG 问答**：查询理解 → 五维混合检索（Dense + BM25 + RRF）→ 重排 →
   上下文组装 → LLM 生成（SSE + 溯源）→ 历史落库。
3. **知识图谱**：LLM 实体关系抽取 → NebulaGraph 分 space 入库 → 子图查询/可视化；
   Nebula 不可用时优雅降级。

详细数据流以旧版 `document-parser-rag-system/docs/ARCHITECTURE.md` 为参照，
新版以本文件为权威。
