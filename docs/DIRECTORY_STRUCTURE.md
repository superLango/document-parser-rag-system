# 目标目录结构

## 1. 仓库总览（目标形态）

```
hansonDoc_RAG/
├── README.md
├── AGENTS.md
├── .gitignore
├── docs/                     # 全部规范（本文档为目录规范）
├── frontend/                 # React 前端
├── backend/                  # Python 后端
├── deploy/                   # 基础设施部署配置
├── scripts/                  # 工具脚本（模型下载等）
└── document-parser-rag-system/   # 旧版冻结基线（重构完成后归档/移除）
```

## 2. 前端结构（React）

```
frontend/
├── index.html
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── tsconfig.json
├── components.json              # shadcn/ui 配置
└── src/
    ├── main.tsx                 # 入口（Provider 装配）
    ├── App.tsx
    ├── app/                     # 应用级装配：router / providers / error-boundary
    ├── api/                     # axios 实例 + 模块化 API（auth/kb/document/extraction/qa/graph/admin/public）
    ├── components/              # 通用组件（ui/ 为 shadcn 生成件，业务组件按域下沉）
    ├── features/                # 业务域（auth/kb/dashboard/admin/embed）
    │   ├── kb/
    │   │   ├── documents/
    │   │   ├── extraction/
    │   │   ├── qa/
    │   │   ├── graph/
    │   │   ├── terms/
    │   │   └── config/
    ├── hooks/                   # 通用 hooks（useSSE/usePagination/useDownload/useKbPermission）
    ├── lib/                     # 工具（utils/traceId/i18n/errorTracking）
    ├── stores/                  # Zustand（auth/settings/kb/graph）
    ├── styles/                  # globals.css + 主题 token
    ├── types/                   # 全局类型定义
    └── locales/                 # i18n 语言包
```

## 3. 后端结构（Python）

```
backend/
├── pyproject.toml（或 requirements.txt）
├── alembic.ini
├── alembic/versions/
├── .env.example
├── Dockerfile
├── start_worker.sh
└── app/
    ├── main.py
    ├── api/
    │   ├── deps.py             # 鉴权 / KBContext / RLS / 限流
    │   └── v1/
    │       ├── router.py
    │       └── endpoints/      # 仅 KB 化 + 公共/系统端点，不保留全局旧端点
    ├── core/                   # config / database / exceptions / response / security / logging
    ├── models/                 # SQLAlchemy ORM（P1 补齐）
    ├── schemas/                # Pydantic 请求/响应
    ├── services/
    │   ├── ocr/                # GLM-OCR 等
    │   ├── popo/               # MinerU-Popo 后处理
    │   ├── vector/             # 五维向量 / BM25 / 分块 / 重建
    │   ├── extraction/         # 抽取管线（v3）
    │   ├── extraction_config/  # 配置中心
    │   ├── graph/              # NebulaGraph
    │   ├── rag/                # RAG 引擎
    │   ├── llm/                # vLLM 封装
    │   ├── embedding/          # bge-m3
    │   ├── term/               # 术语集
    │   ├── kb/                 # KB 生命周期/配置/模板
    │   └── infra/              # storage/cache/notification/export/dashboard
    ├── tasks/                  # arq 任务（process/parse/extract/index_graph/cleanup）
    ├── middleware/             # audit / ip_whitelist / api_version
    ├── domain_templates/       # 4 个领域模板
    └── kb_hooks/               # Hook 机制
```

## 4. 命名规则

- 目录：小写 + 连字符（`extraction-config`、`document-viewer`）。
- Python 文件/包：snake_case；类：PascalCase；常量：UPPER_SNAKE_CASE。
- React 组件文件：PascalCase（`.tsx`）；非组件模块：camelCase（`.ts`）。
- API 路径：`/kbs/{kb_id}/...` 为唯一业务路径，全局旧路径不新增。
