# apps/web

前端骨架（React 19 + TypeScript + Vite 7 + Tailwind 4）。

```powershell
pnpm install
pnpm --filter @hanson/web dev      # http://127.0.0.1:5173
pnpm --filter @hanson/web build
```

开发服务器把 `/v1`、`/health` 代理到 `http://127.0.0.1:8765`；生产可用
`VITE_API_BASE_URL` 指定 API 地址。

## 当前页面

| 路由 | 页面 | 数据 |
|---|---|---|
| `/` | 任务列表 | `GET /v1/jobs` |
| `/jobs/:jobId` | 任务详情 | `GET /v1/jobs/{id}`、`/items`、`/alignment`、`/new-terms` |
| `/dictionary` | 业务词典 | `GET /v1/business-dictionary?type=&q=` |

## 边界

- 骨架阶段只做最少页面，用来验证 API 消费与构建链路；
- M1.9 按 `docs/frontend-scope.md` 迁移 hansonDoc_RAG 的登录/知识库/文档/任务页面，删除旧术语集编辑、抽取配置、RAG/图谱/向量搜索；
- `src/types.ts` 是过渡手写类型；契约稳定后改用 `packages/contracts` 生成类型。
