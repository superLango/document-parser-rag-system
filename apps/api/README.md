# apps/api

平台 API 入口（引擎 + 认证/功能模块/文档/任务）。

```powershell
# 在仓库根目录运行
pip install -e "metal-doc-agent[api,yaml,dev]"
pip install -e "apps/api"

# 初始化管理员
cd apps/api
python -m hanson_api.bootstrap --username admin --password "change-me"
alembic upgrade head
cd ../..

uvicorn hanson_api.main:app --app-dir apps/api --port 8765
```

- 平台实现：`apps/api/hanson_api/`（auth / knowledge bases / documents / tasks / API keys / audit）
- 预览：`/v1/documents/{id}/preview`、`/pages/{n}/image`、`/pages/{n}/layout`（页图 + PP-DocLayoutV3 版面块）
- 数据库：`data/platform/platform.db`（SQLite）；`HANSON_DATABASE_URL` 可切 PostgreSQL
- 引擎实现：`metal-doc-agent/metal_doc_agent/api.py`
- 目标契约：[docs/openapi/standard-extraction.yaml](../../docs/openapi/standard-extraction.yaml)
- 平台面已实现契约：[packages/contracts/openapi.json](../../packages/contracts/openapi.json)（引擎数据端点默认不暴露）
- 安全：平台端点全部要求 JWT 或 `X-API-Key`；分享链接使用 15 分钟 HMAC 令牌；`/v1/jobs*`、`/v1/recipes`、`/v1/batches` 默认移除，确需暴露时强制 `ENGINE_INTERNAL_TOKEN`；登录失败按用户名+IP 限流。

M1.9 P1 将迁移 parsekit 与文档预览；当前平台层已通过 P0 验收。
