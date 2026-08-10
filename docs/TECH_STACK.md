# 技术栈选型

## 1. 前端（React）

| 技术 | 版本策略 | 用途 |
|------|---------|------|
| React | 19.x | UI 框架 |
| TypeScript | 5.6+ | 严格模式 |
| Vite | 5.x/6.x | 构建（开发端口 5174） |
| Tailwind CSS | 4.x | 原子化样式 + 主题 token |
| Radix UI（shadcn/ui 风格） | 最新 | 无样式可访问组件（参考 LightRAG WebUI 方案） |
| Zustand | 4.x/5.x | 轻量状态管理（auth/settings/kb/graph） |
| TanStack Query | 5.x | 服务端状态缓存与请求 |
| Axios | 1.x | HTTP 客户端（拦截器注入 JWT/trace_id） |
| react-router | 7.x | 路由 |
| react-i18next | 15.x | 国际化（zh-CN / en-US） |
| react-markdown + remark-math + rehype-katex | 最新 | Markdown / 公式渲染 |
| mermaid | 11.x | 流程图/时序图渲染 |
| Sigma.js + Graphology | 最新 | 知识图谱可视化（参考 LightRAG，替代 cytoscape） |
| pdfjs-dist | 3.x | PDF 预览 |
| Chart.js | 4.x | 仪表盘图表 |
| pnpm | 10+ | 包管理 |

## 2. 后端（Python，沿用现有成熟选型）

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 运行时 |
| FastAPI | ≥0.115 | Web 框架 |
| Pydantic | 2.x | 校验 |
| SQLAlchemy 2 (asyncpg) + Alembic | ≥2.0 / ≥1.13 | 异步 ORM + 迁移 |
| arq | ≥0.26 | 异步任务队列 |
| pymilvus | ≥2.4 | 向量库 |
| FlagEmbedding / sentence-transformers | ≥1.2 / ≥3.0 | bge-m3 嵌入 |
| langextract | ≥1.6 | LangExtract 抽取引擎 |
| mineru | ==3.4.3 | 版面分析 |
| boto3 | ≥1.34 | S3 兼容存储 |
| nebula-python | 最新 | NebulaGraph |
| structlog + prometheus-fastapi-instrumentator | 最新 | 日志 + 指标 |
| ruff + mypy + pytest | 最新 | 质量与测试 |
| uv（可选） | 最新 | 依赖/虚拟环境管理（默认仍兼容 pip + venv） |

## 3. 数据与基础设施

| 组件 | 版本 | 用途 |
|------|------|------|
| PostgreSQL | 16 | 元数据/配置（RLS） |
| Redis | 7+ | 缓存（db0）+ 队列（db1） |
| MinIO / S3 兼容（SeaweedFS） | — | 对象存储 |
| Milvus | 2.4 | 向量库 |
| NebulaGraph | — | 图数据库 |
| vLLM | 最新 | GLM-OCR(9977) / Qwen(9988) / Popo(9999) |

## 4. 版本锁定策略

- 前端：`pnpm-lock.yaml` 提交入库，CI 使用 `pnpm install --frozen-lockfile`。
- 后端：`requirements.txt` 锁定主版本范围，重构建时导出精确版本到
  `requirements.lock`。
- 模型服务名（`--served-model-name`）与 `.env` 中 `*_MODEL` 必须**完全一致
  （大小写敏感）**，统一拼写为 `Qwen3.6-35B-A3B-FP8`。
