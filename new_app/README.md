# new_app

Hanson 标准拆分平台重构代码目录。当前为 M0 脚手架，只包含服务健康检查、契约占位、前端骨架与本地基础设施，不包含业务逻辑。

## 服务

| 服务 | 端口 | 启动 |
|---|---|---|
| api-gateway | 8000 | `uvicorn services.api_gateway.main:app --port 8000` |
| orchestration | 8001 | `uvicorn services.orchestration.main:app --port 8001` |
| ocr | 8002 | `uvicorn services.ocr.main:app --port 8002` |
| agent | 8003 | `uvicorn services.agent.main:app --port 8003` |
| sandbox | 8004 | `uvicorn services.sandbox.main:app --port 8004` |
| recipe-registry | 8005 | `uvicorn services.recipe_registry.main:app --port 8005` |
| review | 8006 | `uvicorn services.review.main:app --port 8006` |
| web | 5173 | `npm run dev` |

统一健康检查：`GET /healthz` 返回：

```json
{"status": "ok", "service": "api-gateway", "version": "0.0.0"}
```

## 本地启动

```powershell
cd new_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn services.api_gateway.main:app --reload --port 8000
```

前端：

```powershell
cd new_app/web
npm install
npm run dev
```

基础设施（Postgres/MinIO/Redis + 七服务）：

```powershell
cd new_app
docker compose -f deploy/compose/docker-compose.yml up -d
```

## 目录

```text
new_app/
├── services/          # 七个服务骨架
├── packages/          # contracts / domain / observability
├── web/               # 前端骨架
├── deploy/            # compose / k8s
├── tests/             # 测试
├── scripts/           # 开发、导入、基准脚本
├── docs/              # 架构、需求、决策、计划
└── PROVENANCE.md      # 旧代码复用来源记录
```

## 约束

- 所有新代码只放在 `new_app/`。
- 不 import `legacy/` 或旧包。
- 公开 API 使用 `/v1`，内部 API 使用 `/internal`。
- 本地对象存储使用 MinIO。
- 当前 1 人开发，按里程碑串行推进。
