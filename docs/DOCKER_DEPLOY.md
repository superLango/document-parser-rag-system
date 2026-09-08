# Docker 部署手册（hansonDoc_RAG · 全容器化）

> 配套方案：[DOCKER_BUILD_PLAN.md](./DOCKER_BUILD_PLAN.md) · 2026-08-23

## 一、前置条件

- Docker + Docker Compose；
- NVIDIA 容器运行时（nvidia-container-toolkit，GPU 用于嵌入/重排/版面）；
- 宿主机 vLLM 独立运行：GLM-OCR（:9977）、LLM（:9988）。

## 二、构建

```bash
bash scripts/docker_build.sh
```

- `hansondoc-backend`：python:3.13 + torch cu130 + 全量依赖，**不含小模型** ≈ 6.7G；
- `hansondoc-frontend`：vite 构建 → nginx ≈ 50M。

**小模型不进镜像**（离线部署传 tar 体积考虑）：模型由宿主机目录卷挂载（`models/bge-m3`、`models/bge-reranker-v2-m3`、`models/pp_doclayoutv3_finetuned_v2`，约 5G），单独传输一次即可；**改后端代码重建镜像时模型目录无需重传**。

## 三、部署

```bash
cp .env.example .env   # 修改密码等
# 部署机放置小模型目录（与镜像 tar 分离传输）：
#   models/bge-m3、models/bge-reranker-v2-m3、models/pp_doclayoutv3_finetuned_v2
bash scripts/db_export.sh   # 从现有 PostgreSQL 导出 backup/dump.sql（首次需要）
docker compose up -d
```

**离线部署传输清单**（按需重传）：
- 首次：`hansondoc-backend.tar`（6.7G）+ `hansondoc-frontend.tar`（50M）+ 模型目录（5G）+ `backup/dump.sql`；
- 改后端代码：只重传 `hansondoc-backend.tar`（模型目录、前端、数据库不动）。

首次启动 PG 容器自动初始化：建 vector 扩展 → 恢复 dump → 清理（保留系统表 + 航天航空 KB 的抽取配置/术语集，清空文档/向量，删除其他知识库）。

## 四、访问

| 入口 | 地址 |
|---|---|
| 前端 | http://<host>:18080 |
| 后端接口（含系统对接） | http://<host>:18000 |
| PostgreSQL | <host>:15432（hansondoc / 密码见 .env） |
| Redis | <host>:16379（密码 REDIS_PASSWORD） |
| MinIO | <host>:19000 / 控制台 19001 |

## 五、数据初始化校验

```bash
docker exec hansondoc-postgres-1 psql -U hansondoc -d hanson_doc_rag -c "SELECT count(*) FROM knowledge_bases;"  # 期望 1
docker exec hansondoc-postgres-1 psql -U hansondoc -d hanson_doc_rag -c "SELECT count(*) FROM documents;"       # 期望 0
docker exec hansondoc-postgres-1 psql -U hansondoc -d hanson_doc_rag -c "SELECT count(*) FROM terms;"          # 期望 967
```

## 六、系统对接接口（容器内已就绪）

- 上传：`POST /api/v1/integration/upload`（file + kb_id + prompt_id）
- 状态：`GET /api/v1/integration/tasks/{task_id}/status`
- 结果：`GET /api/v1/integration/tasks/{task_id}/result`
- 重触发：`POST /api/v1/integration/tasks/{task_id}/retrigger`
- 结果页：`http://<host>:18080/integration/task/{task_id}`

详见 [INTEGRATION_API.md](./INTEGRATION_API.md)。

## 七、注意事项

1. **OCR/LLM 依赖宿主 vLLM**：容器通过 `host.docker.internal` 访问宿主 9977/9988；vLLM 未启动时 OCR/抽取任务会失败，`status` 接口返回 `error` 原因。
2. **模型预热**：容器启动仅预热嵌入/重排/版面（跳过外部 vLLM），约 30s。
3. **重新初始化数据**：删除 PG 卷后 `docker compose up -d` 会重新执行 initdb（需重新导出 dump）。
4. 首次构建后端镜像较慢（torch cu130 下载 + 模型 COPY），约 10 分钟+。
