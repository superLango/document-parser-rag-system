# packages/contracts

契约层，供 `apps/api`、`apps/web` 与外部对接使用。

| 文件 | 来源 | 用途 |
|---|---|---|
| `openapi.json` | `apps/api/tools/export_openapi.py` 从组合后的 FastAPI 导出 | 当前已实现契约（source of truth for implemented routes） |
| `../../docs/openapi/standard-extraction.yaml` | 手写草案 | M1.9 目标契约；`x-status` 标记 implemented/planned |

## 刷新已实现契约

```powershell
cd apps/api
python tools\export_openapi.py
```

脚本会从组合后的 FastAPI 应用（引擎 + 平台）导出并写入 `packages/contracts/openapi.json`。修改 API 路由或响应模型后必须重新导出。

## 后续

- M1.9：用 `openapi-typescript` 从 `openapi.json` 生成 `packages/contracts/src/api.d.ts`，前端不再手写类型；
- 契约评审以 `docs/openapi/standard-extraction.yaml` 为准，目标端点实现后再把 `x-status` 改为 `implemented`；
- `metal-doc-agent/tests/test_openapi.py` 会校验“标记为 implemented 的端点必须真实存在”。
