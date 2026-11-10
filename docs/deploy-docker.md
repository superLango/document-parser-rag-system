# Docker 一键部署手册

> 适用分支：`doc_parse`（开发分支：`wjh-doc_parse`）
> 部署形态：单机 Docker Compose，包含 Web、Platform API、Engine API、Worker、PostgreSQL。
> 模型服务（GLM-OCR / 版面 / Qwen）不包含在 Compose 内，通过环境变量接入已有服务。

## 1. 架构与端口

```text
浏览器 / 外部系统
   │  :8080
   ▼
 nginx (web)
   ├── 静态前端
   └── /v1、/api/v1/integration → platform-api :8000
                                     │
                                     ├── PostgreSQL :5432（平台库）
                                     ├── engine-api :8010（内部）
                                     └── worker-prod / worker-explore
                                             │
                                             └── GLM-OCR / Layout / Qwen（外部模型服务）
```

| 服务 | 容器名/镜像 | 端口 | 说明 |
|---|---|---|---|
| web | `hanson-r1-web` | 8080 | 前端与 nginx 反向代理 |
| platform-api | `hanson-r1-platform-api` | 8000 | 认证、知识库、文档、对接接口 |
| engine-api | `hanson-r1-engine-api` | 8010（内部） | 解析引擎 API |
| worker-prod | `hanson-r1-worker-prod` | 无 | 正式解析队列 |
| worker-explore | `hanson-r1-worker-explore` | 无 | 探索队列 |
| postgres | `postgres:16-alpine` | 内部 5432 | 平台数据库 |
| redis/minio | 可选 profile `extras` | 9000/9001 | 备份/对象存储预留 |

## 2. 环境要求

- Docker Engine 24+，Docker Compose v2（`docker compose version`）。
- 建议 8 核 CPU / 16 GB 内存 / 50 GB 以上磁盘；解析任务越多，数据卷越大。
- 能访问模型服务地址（默认 `192.168.188.75` 的 9977/9978/9979/9991）。
- 本手册以 Linux 服务器为准；Windows/macOS 使用 Docker Desktop 时，需注意 Compose 中 worker 使用了 `network_mode: host`，如不可用请改为 bridge 并把模型地址换成宿主可达地址。

## 3. 获取代码

```bash
git clone -b doc_parse git@github.com:superLango/document-parser-rag-system.git hanson_doc_parse
cd hanson_doc_parse
```

仓库不包含测试用标准 PDF（`汉唐标准/`、`标准文件/`）和体积较大的运行产物；上传自己的 PDF 即可开始解析。

## 4. 配置环境变量

```bash
cd infra/docker
cp .env.example .env
```

编辑 `.env`，至少确认：

```bash
HANSON_ENV=production
HANSON_SECRET_KEY=<32 位以上随机串>          # 例：openssl rand -hex 32
POSTGRES_PASSWORD=<强密码>

# 默认免登录（适合内网/嵌入）；需要登录时改为 true
HANSON_REQUIRE_AUTH=false

# 模型服务（按实际地址修改）
GLM_OCR_BASE_URL=http://192.168.188.75:9977/v1
LAYOUT_SERVICE_URL=http://192.168.188.75:9979
QWEN_BASE_URL=http://192.168.188.75:9991/v1
QWEN_MODEL=Qwen3.6-35B-A3B-NVFP4
```

说明：

- `HANSON_REQUIRE_AUTH=false` 时所有接口不做鉴权，统一使用 `embed_guest`；设置为 `true` 后写接口需要 JWT 或 `X-API-Key`。
- 修改 `POSTGRES_PASSWORD` 后无需手工改连接串，Compose 会自动拼出 `HANSON_DATABASE_URL`。
- 生产环境不要使用 `.env.example` 中的占位密码。

## 5. 构建镜像

在 `infra/docker` 目录执行：

```bash
docker compose -p hanson-r1 build
```

如需国内镜像加速：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
NPM_REGISTRY=https://registry.npmmirror.com \
docker compose -p hanson-r1 build
```

构建说明：

- 统一使用 Docker 构建，不要求宿主机安装 Python/Node。
- `.dockerignore` 已排除测试标准文件、运行产物、前端 `dist` 和 `node_modules`。
- `metal-doc-agent/configs` 会随镜像打入，其中包含当前业务词典
  `hanson-ht-64c316a7`（`configs/dictionaries/*.json` 与 `configs/business_dictionary.hanson.json`）。

## 6. 启动

```bash
docker compose -p hanson-r1 up -d
docker compose -p hanson-r1 ps
```

启动顺序由依赖关系保证：

1. `postgres` 健康检查通过；
2. `platform-api` 启动时自动执行 `alembic upgrade head`；
3. `engine-api` 通过 `/ready` 后启动 worker；
4. 最后启动 `web`。

查看状态与日志：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/healthz
docker compose -p hanson-r1 logs -f platform-api
```

## 7. 数据库

- 数据库：PostgreSQL 16，容器内地址 `postgres:5432`，库名/用户均为 `hanson`。
- 表结构由 Alembic 管理，迁移文件：`apps/api/alembic/versions/`。
- 首次启动自动建表；也可以手动执行：

```bash
docker compose -p hanson-r1 exec platform-api alembic upgrade head
docker compose -p hanson-r1 exec platform-api alembic current
docker compose -p hanson-r1 exec platform-api alembic history
```

- 数据持久化卷：`hanson-r1_postgres-data`、`hanson-r1_platform-data`、`hanson-r1_engine-data`。
- 备份：

```bash
docker compose -p hanson-r1 exec -T postgres \
  pg_dump -U hanson -d hanson -Fc > hanson_$(date +%F).dump
```

- 恢复：

```bash
cat hanson_2026-11-10.dump | docker compose -p hanson-r1 exec -T postgres \
  pg_restore -U hanson -d hanson --clean --if-exists
```

## 8. 初始化管理员（可选）

默认免登录模式可直接使用；需要严格权限或后台管理时：

```bash
docker compose -p hanson-r1 exec platform-api \
  python -m hanson_api.bootstrap --username admin --password 'ChangeMe-123!'
```

然后把 `.env` 中 `HANSON_REQUIRE_AUTH` 改为 `true`，重启 `platform-api` 和 `web`。

访问：

- Web：`http://<host>:8080`
- API：`http://<host>:8000`
- 对接结果页：`http://<host>:8080/integration/task/<task_id>`

## 9. 业务词典

当前版本：`hanson-ht-64c316a7`，由《汉唐项目大类检测方法汇总》导入。

文件位置：

```text
metal-doc-agent/configs/dictionaries/
  categories.json   项目大类
  items.json        检测项目
  methods.json      试验方法
metal-doc-agent/configs/business_dictionary.hanson.json   单体快照（引擎本地运行使用）
metal-doc-agent/configs/dictionary_backup_<时间戳>/        导入前备份
```

更新词典：

1. 备份当前 `configs/dictionaries` 和 `business_dictionary.hanson.json`；
2. 按同样结构写入新版本（`version`、`entries`），或替换为新的分类结果；
3. 同步更新 `business_dictionary.hanson.json`；
4. 重新构建并重启 `platform-api`、`engine-api`、worker；
5. 已有知识库副本会在下次解析时按版本标记自动同步（旧副本会备份为
   `dictionaries/<kb_id>.bak-<时间戳>`）。

验证词典：

```bash
curl http://127.0.0.1:8000/v1/business-dictionary?limit=1
```

返回的 `version` 应为当前版本；解析结果的 `alignment.json` 中
`dictionary_version` 也应一致。

## 10. 已解析数据资产（跨标准引用）

仓库包含跨标准直接可用的小体积资产：

```text
markdown/                                  409 份已解析标准/协议 Markdown
metal-doc-agent/data/standards_library/    标准目录、索引、跨标准扫描任务
metal-doc-agent/data/business_terms/       业务术语快照
```

Compose 会把它们只读挂载到容器：

- `../../markdown:/app/markdown:ro`
- `../../metal-doc-agent/data/standards_library:/app/metal-doc-agent/data/standards_library:ro`

跨标准补全通过 `standards_library/catalog.json`、`index.json` 与 `markdown/` 定位来源标准；新增已解析标准时，把 Markdown 放入 `markdown/`，再执行：

```bash
cd metal-doc-agent
python tools/scan_markdown_library.py
python tools/scan_cross_standard_markdown.py
```

## 11. 上传并验证一个文档

1. 打开 `http://<host>:8080`；
2. 进入「标准拆分 → 文档解析」，创建/选择知识库，上传 PDF；
3. 点击解析，等待 OCR 与结构化抽取完成；
4. 打开结构化抽取详情页，确认类别、记录、证据可查看；
5. 在结果页使用「问题反馈」「导出」，导出格式包括 Schema JSON / JSON / CSV / XLSX。

外部系统一站式对接（与 hansonDoc_RAG 兼容）：

```bash
# 上传（免登录模式无需鉴权头；严格模式需 X-API-Key 或 Bearer）
curl -X POST "http://<host>:8000/api/v1/integration/upload?kb_id=<kb_id>&prompt_id=<prompt_id>" \
  -F "file=@document.pdf"

# 查询
curl "http://<host>:8000/api/v1/integration/tasks/<task_id>/status"
curl "http://<host>:8000/api/v1/integration/tasks/<task_id>/result"
```

## 12. 升级与回滚

```bash
cd hanson_doc_parse
git pull origin doc_parse
cd infra/docker
docker compose -p hanson-r1 build
docker compose -p hanson-r1 up -d
```

回滚：

```bash
git checkout <上一个提交>
docker compose -p hanson-r1 build
docker compose -p hanson-r1 up -d
```

数据库迁移回滚：

```bash
docker compose -p hanson-r1 exec platform-api alembic downgrade -1
```

> 升级前请先备份 `postgres-data`、`platform-data`、`engine-data` 三个卷。

## 13. 常见问题

| 现象 | 处理 |
|---|---|
| 页面能打开但接口 502 | 查看 `platform-api` 日志；确认 8000 端口与数据库健康 |
| 解析任务一直 pending | 检查 `worker-prod` 日志、模型服务是否可达 |
| OCR/抽取失败 | 检查 `.env` 的 `GLM_OCR_BASE_URL`、`LAYOUT_SERVICE_URL`、`QWEN_BASE_URL`；先 `curl` 模型健康接口 |
| 上传 413 | 调整 `client_max_body_size` 与平台上传大小限制 |
| 词典未生效 | 确认 `/v1/business-dictionary` 的 version；确认知识库词典目录的 `.dictionary_source_version` 已更新 |
| 数据库连不上 | 检查 `POSTGRES_PASSWORD` 是否与 `hanson` 用户一致；不要手工改 `HANSON_DATABASE_URL` 里的库名 |
| 前端构建失败 | 检查 `NPM_REGISTRY` 与网络；确认 `pnpm-lock.yaml` 未被修改 |

## 14. 安全提示

- 默认免登录 + 允许 iframe 嵌入，建议部署在内网或网关之后。
- 对外暴露时设置 `HANSON_REQUIRE_AUTH=true`、`HANSON_ALLOW_EMBED=false`，并为外部系统创建最小权限 API Key。
- 不要提交 `.env`、`secret.key`、数据库密码或上传文件到 Git。
- 测试标准 PDF 不随仓库分发，请在上传前确认文件版权与数据合规。
