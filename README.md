# Hanson Metal Document Platform

金属材料标准 / 制造大纲 / 技术协议的结构化拆分平台。引擎负责表格解析、列绑定、项目清单、条款与业务对齐；平台负责文档、任务、复核与业务词典。

## 快速部署（Docker）

完整步骤见 [docs/deploy-docker.md](docs/deploy-docker.md)：

```bash
git clone -b doc_parse git@github.com:superLango/document-parser-rag-system.git
cd document-parser-rag-system/infra/docker
cp .env.example .env      # 填写 HANSON_SECRET_KEY / POSTGRES_PASSWORD / 模型地址
docker compose -p hanson-r1 build
docker compose -p hanson-r1 up -d
```

默认免登录，访问 `http://<host>:8080`；数据库、词典、模型服务和升级回滚说明均在部署手册中。

当前进度：M1.8 完成（三类术语集接入），M1.9a 工程骨架与 API 契约落地，M1.9 前端/后端平台化待推进。

## 目录

```text
apps/
  api/         FastAPI 入口（当前为引擎薄封装）
  worker/      单任务 worker 入口
  web/         React 19 + TS + Vite + Tailwind 骨架
packages/
  contracts/   已实现 OpenAPI（openapi.json）与契约说明
docs/
  engineering.md          工程规范
  openapi/                目标 API 草案（implemented/planned）
  frontend-scope.md       前端取舍
  hansonDoc_RAG-audit.md  迁移审计
metal-doc-agent/          引擎（解析、配方、项目清单、业务对齐、评测）
metal-standard-agent-plan/  里程碑与阶段方案
```

## 快速开始

```powershell
# 引擎依赖
pip install -e "metal-doc-agent[api,yaml,dev]"
# 平台依赖（认证、知识库、文档、任务）
pip install -e "apps/api"

# 初始化平台管理员
cd apps/api
python -m hanson_api.bootstrap --username admin --password "change-me"
alembic upgrade head
cd ../..

# 引擎测试
cd metal-doc-agent
python -m unittest discover -s tests -q
cd ..

# 平台测试
cd apps/api
python -m unittest discover -s tests -q
cd ../..

# API（引擎 + 平台）
uvicorn hanson_api.main:app --app-dir apps/api --port 8765

# 前端
pnpm install
pnpm --filter @hanson/web dev      # http://127.0.0.1:5173

# Worker（消费已创建任务；--watch 常驻，--once 单次）
python apps/worker/main.py --job-id <job_id>
python apps/worker/main.py --watch
python apps/worker/main.py --once
```

平台接口（P0/P1）：

```text
POST /v1/auth/login              GET /v1/auth/me
GET/POST /v1/knowledge-bases     GET /v1/knowledge-bases/{id}
GET/POST /v1/documents           GET /v1/documents/{id}
POST /v1/documents/{id}/parse    GET /v1/documents/{id}/items|result|evidence|new-terms|clauses|links|coverage-audit
GET  /v1/documents/{id}/preview  GET /v1/documents/{id}/pages/{n}/image|layout
GET  /v1/documents/{id}/reviews  POST /v1/documents/{id}/new-terms/review
POST /v1/documents/{id}/share    GET /v1/share/{token}
GET /v1/tasks                    GET /v1/tasks/{job_id}
POST /v1/tasks/{job_id}/retry
GET/POST /v1/api-keys            DELETE /v1/api-keys/{id}
GET /v1/audit-logs
```

上传并解析（先登录，再在知识库下上传并创建解析任务）：

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/auth/login `
  -ContentType application/json -Body '{"username":"admin","password":"<password>"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$kb = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/knowledge-bases `
  -Headers $headers -ContentType application/json -Body '{"name":"标准库"}'

curl.exe -X POST http://127.0.0.1:8765/v1/documents `
  -H "Authorization: Bearer $($login.access_token)" `
  -F "kb_id=$($kb.id)" -F "file=@标准文件\Q-Du 302-2015.md"

curl.exe -X POST "http://127.0.0.1:8765/v1/documents/<document_id>/parse" `
  -H "Authorization: Bearer $($login.access_token)"
```

> 引擎 `/v1/jobs*`、`/v1/recipes`、`/v1/batches` 只在内网 `engine-api:8010` 提供，默认不经平台端口暴露；确需暴露时设置 `ENGINE_INTERNAL_TOKEN` 并携带 `X-Engine-Token`。

## 契约

- 目标契约：[docs/openapi/standard-extraction.yaml](docs/openapi/standard-extraction.yaml)（`x-status: implemented|planned`）
- 平台面已实现契约：[packages/contracts/openapi.json](packages/contracts/openapi.json)；引擎 API 契约在 `metal-doc-agent` 内，不经平台端口暴露
- 刷新：`cd apps/api && python tools\export_openapi.py`
- 校验：`metal-doc-agent/tests/test_openapi.py` 检查引擎 implemented 端点必须真实存在

## 文档

- 工程规范：[docs/engineering.md](docs/engineering.md)
- 阶段方案：[metal-standard-agent-plan/development-plan-v3.md](metal-standard-agent-plan/development-plan-v3.md)
- 引擎说明：[metal-doc-agent/README.md](metal-doc-agent/README.md)
