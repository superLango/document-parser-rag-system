# 工程规范与仓库骨架（M1.9a）

> 日期：2026-10-27
> 状态：骨架可运行（API / worker / web 构建通过；契约校验纳入测试）
> 上位文档：`metal-standard-agent-plan/stages/03c-M1.9a-需求确认与工程骨架.md`

---

## 1. 原则

1. **引擎与平台分离**：引擎（解析、列绑定、项目清单、业务对齐）不做认证、数据库、知识库；平台通过 HTTP 调引擎。
2. **前端驱动后端**：页面需要什么字段，API 就提供什么；不为“以后可能用”提前建模。
3. **未审计代码不迁移**：hansonDoc_RAG 的迁移范围以 `docs/hansonDoc_RAG-audit.md` 为准。
4. **契约先行**：目标契约 `docs/openapi/standard-extraction.yaml`；已实现契约由代码导出，测试校验一致性。
5. **1.35 只跑模型**：业务库、队列、Web、worker 都在开发机/业务机。

---

## 2. 目录结构（当前）

```text
f:\hanson\hanson_doc_parse\
├─ apps\
│  ├─ api\                 # FastAPI 入口（薄封装 metal_doc_agent.api）
│  ├─ worker\              # 单任务 worker 入口
│  └─ web\                 # React + TS + Vite + Tailwind 骨架
├─ packages\
│  └─ contracts\           # 已实现 OpenAPI（openapi.json）与契约说明
├─ docs\
│  ├─ openapi\standard-extraction.yaml   # 目标 API 草案
│  ├─ engineering.md       # 本文
│  ├─ frontend-scope.md    # 前端取舍
│  ├─ frontend-modification.md
│  └─ hansonDoc_RAG-audit.md
├─ metal-doc-agent\        # 引擎（Python 包 + 测试 + 工具 + 评测）
│  ├─ metal_doc_agent\     # 引擎实现（后续迁入 packages/engine）
│  ├─ configs\             # 配方、别名、词典快照、覆盖模板
│  ├─ eval\                # 评测报告
│  ├─ goldset\              # 金标
│  ├─ tests\               # unittest
│  └─ tools\               # 导入、评测、pilot、导出脚本
├─ package.json            # pnpm workspace 根
├─ pnpm-workspace.yaml
└─ .github\workflows\ci.yml
```

M1.9 目标结构：`packages/engine`、`packages/contracts`、`packages/parsers`、
`packages/adapters`、`packages/knowledge`；`metal-doc-agent/` 逐步迁入并保留
CLI/测试入口。当前不搬目录，避免大规模改动与双份维护。

---

## 3. 技术栈

| 层 | 当前 | 目标 |
|---|---|---|
| 引擎 | Python 3.11+、Pydantic v2、lxml、unittest | 3.12、ruff、mypy |
| API | FastAPI、uvicorn、python-multipart | 增加认证/RBAC、SQLAlchemy 2、Alembic |
| Worker | 单任务进程（JobStore 文件） | arq + Redis（M1.9/M3） |
| 前端 | React 19、TypeScript 5、Vite 7、Tailwind 4、pnpm 11 | 增加 shadcn/ui、生成式 API 类型 |
| 契约 | OpenAPI 3.1（YAML 草案 + JSON 导出） | 契约测试 + 前端类型生成 |

版本以 `apps/web/package.json` 与 `metal-doc-agent/pyproject.toml` 为准；新增依赖需同时更新锁文件。

---

## 4. 运行方式

```powershell
# 1) 引擎依赖
pip install -e "metal-doc-agent[api,yaml,dev]"

# 2) API
uvicorn main:app --app-dir apps/api --port 8765

# 3) Web
pnpm install
pnpm --filter @hanson/web dev

# 4) Worker（消费一条任务）
python apps/worker/main.py --job-id <job_id>
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `METAL_DOC_HOME` | `metal-doc-agent/` | 配置根目录 |
| `METAL_DOC_DATA` | `metal-doc-agent/data` | 任务/上传数据 |
| `BUSINESS_DICTIONARY_SNAPSHOT` | `configs/business_dictionary.hanson.json` | 业务词典快照 |
| `METAL_DOC_ALIGNMENT` | `1` | 关闭业务对齐 |
| `HANSON_REQUIRE_AUTH` | `false` | 嵌入模式是否要求登录；`false` 时无令牌请求映射固定访客 |
| `HANSON_ANONYMOUS_USERNAME` | `embed_guest` | 免登录访客用户名（首次访问自动创建） |
| `HANSON_ALLOW_EMBED` | `true` | 允许 iframe 嵌入（`X-Frame-Options` 关闭、`frame-ancestors *`） |
| `VITE_API_BASE_URL` | 空（同源/代理） | 前端 API 地址 |
| `GLM_OCR_BASE_URL` / `QWEN_BASE_URL` / `LAYOUT_SERVICE_URL` | 无 | 1.35 模型服务（当前 `192.168.1.35`） |

---

## 5. 契约流程

1. 目标契约：`docs/openapi/standard-extraction.yaml`，每个操作带 `x-status`：
   - `implemented`：必须能在当前 FastAPI 应用中路由到；
   - `planned`：M1.9 目标，未实现前不得在前端调用。
2. 已实现契约：`metal-doc-agent/tools/export_openapi.py` 导出 `packages/contracts/openapi.json`；
3. 校验：`metal-doc-agent/tests/test_openapi.py`
   - YAML 可解析、目标路径齐全、每个操作有 `operationId` 与 `x-status`；
   - `implemented` 路由必须存在于运行中的应用；
   - 导出文件存在且包含核心路径。
4. 前端类型：当前手写 `apps/web/src/types.ts`；M1.9 改为从 `openapi.json` 生成。

新增/修改端点时：

```text
改代码 → 改 YAML（x-status）→ 跑 export_openapi.py → 跑 unittest
```

---

## 6. 数据与产物

单次任务产物目录保持“可校验审计包”：

```text
result.json / evidence.jsonl / audit.md / trace.json / artifacts.json
column_bindings.json / item_inventory.json / item_inventory_aligned.json
alignment.json / new_terms.json / clauses.jsonl / links.json / coverage_audit.json
tablegrid/T*.json / pages.json / outline.json / references.json / coverage_plan.json
```

`artifacts.json` 记录 SHA256/大小；`GET /v1/jobs/{id}/artifacts/verify` 校验完整性。
新增产物必须登记到 `metal_doc_agent/artifacts.py` 的 `ROLE_MAP`（默认 optional）。

---

## 7. 测试与 CI

本地：

```powershell
cd metal-doc-agent
python -m unittest discover -s tests -q

cd ..
pnpm --filter @hanson/web typecheck
pnpm --filter @hanson/web test
pnpm --filter @hanson/web build
pnpm e2e
```

`pnpm e2e` 用隔离数据库启动 API（8765）与 Web（5173），以 mock OCR/抽取跑真实 Chromium 主链路：登录 → 建知识库 → 上传 → 解析 → 结果记录 → 退出；运行痕迹保留在 `e2e/.tmp`（失败时）。

CI（`.github/workflows/ci.yml`）：

| Job | 内容 |
|---|---|
| engine | Python 3.12 安装 `[dev,api,yaml]`，跑 unittest（含 OpenAPI 契约测试） |
| web | pnpm 11 + Node 22，`pnpm install --frozen-lockfile`、typecheck、vitest、build |

尚未接入（M1.9 补齐）：

- ruff / mypy（当前环境未安装，避免骨架阶段引入大量历史告警）；
- pytest 迁移（当前 unittest 已覆盖，迁移时统一）；
- PostgreSQL/Alembic 契约测试；
- E2E（上传 → 拆分 → 复核）本地自动化已接入 `pnpm e2e`，CI 尚未运行；依赖扫描已接入 `pip-audit`（见 10.16）。

---

## 8. 代码约定

- 引擎不得 import 平台模块；平台只能通过 `metal_doc_agent.*` 公共入口或 HTTP 调引擎。
- 产物/契约字段使用 Pydantic 模型，禁止裸 dict 传递核心数据（`summary/coverage` 等统计除外）。
- 错误分两类：用户输入错误返回 4xx；引擎内部异常记录 trace 并保持任务 `failed`，不得返回假结果。
- 上传限制 50 MB、只允许 `.md`/`.pdf`；文件路径必须校验在数据目录内。
- 日志脱敏：不打印 API Key、上传原文；证据引用截断到 300 字。
- 新增配置优先放 `configs/*.json`，不写死在代码里；配置变更需带版本或可追溯哈希。

---

## 9. 阶段状态与下一步

M1.9a 本轮完成：

- [x] 目标 OpenAPI 草案（含 implemented/planned 标记）
- [x] 已实现契约导出与一致性测试
- [x] `apps/api`、`apps/worker`、`apps/web` 骨架
- [x] pnpm workspace、锁文件、CI（engine + web）
- [x] 工程规范（本文）

待办：

- [ ] 信息架构文档（页面/路由/状态图）
- [ ] 模块处置清单独立成文（当前在审计报告第 2 节）
- [ ] 前端功能矩阵业务确认
- [ ] ruff/mypy、E2E、部署 compose

---

## 10. P0 平台层（2026-10-27）

P0 在 `apps/api/hanson_api` 落地认证、知识库、文档、任务、API Key 与审计。

### 10.1 模块

```text
apps/api/hanson_api/
├─ config.py      # 平台数据目录、DB URL、签名密钥、令牌有效期
├─ db.py          # SQLAlchemy 2 engine/session、建表
├─ models.py      # users/knowledge_bases/members/documents/document_tasks/api_keys/audit_logs
├─ security.py    # bcrypt、JWT、API Key 哈希、HMAC 分享令牌
├─ schemas.py     # Pydantic DTO
├─ router.py      # /v1/auth、/v1/knowledge-bases、/v1/documents、/v1/tasks、/v1/api-keys、/v1/audit-logs
└─ bootstrap.py   # 初始化管理员
```

数据库：

- 本地默认 `data/platform/platform.db`（SQLite，WAL 不需要额外配置）；
- 生产用 `HANSON_DATABASE_URL` 指向 PostgreSQL；
- 迁移：`alembic upgrade head`（`apps/api/alembic/versions`），支持 downgrade；
- 开发/测试用 `init_db()` 直接建表，生产以 Alembic 为准。

### 10.2 安全（关闭 A1/A2）

| 审计项 | 关闭方式 |
|---|---|
| A1 无认证 integration + superuser 绕过 RLS | 不迁移旧入口；所有平台端点强制 JWT 或 `X-API-Key`；每个文档/任务校验知识库成员；无 superuser 会话；引擎端口可选 `ENGINE_INTERNAL_TOKEN` 守卫 |
| A2 独立结果页无登录 | 改用 15 分钟 HMAC 签名令牌（`POST /v1/documents/{id}/share` → `GET /v1/share/{token}`），过期或篡改即 401 |

其他约束：

- API Key 只存 SHA-256 哈希，明文只在创建响应出现一次；可撤销、带 scopes；
- 密码 bcrypt；JWT HS256，默认 8 小时；
- 上传限制 50 MB、只允许 `.md/.pdf`、文件名只取 basename、落盘在平台数据目录；
- 审计记录登录、知识库创建、上传、解析、分享、Key 创建/撤销、任务重试。

### 10.3 运行

```powershell
pip install -e "metal-doc-agent[api,yaml,dev]"
pip install -e apps/api

# 初始化管理员（示例，生产请改密码）
cd apps/api
python -m hanson_api.bootstrap --username admin --password "change-me"

# 迁移（可选；开发环境 init_db 会自动建表）
alembic upgrade head

# API
cd ../..
uvicorn main:app --app-dir apps/api --port 8765
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HANSON_PLATFORM_DATA` | `data/platform` | 平台数据目录（DB、上传、密钥） |
| `HANSON_DATABASE_URL` | `sqlite:///data/platform/platform.db` | 数据库连接 |
| `HANSON_SECRET_KEY` | 自动生成 `secret.key` | JWT 与分享令牌签名 |
| `HANSON_ACCESS_TOKEN_MINUTES` | `480` | 访问令牌有效期 |
| `HANSON_SHARE_TOKEN_MINUTES` | `15` | 分享令牌有效期 |
| `HANSON_INLINE_JOBS` | `1` | `1` 请求内后台执行；`0` 只入队，交给 worker |
| `HANSON_ENGINE_ROOT` | `metal-doc-agent` | 词典与 override 所在引擎目录 |
| `ENGINE_INTERNAL_TOKEN` | 空 | 设置后 `/v1/jobs`、`/v1/recipes` 需 `X-Engine-Token` |

### 10.4 前端（P0）

| 路由 | 页面 |
|---|---|
| `/login` | 登录 |
| `/kb` | 知识库列表/创建 |
| `/kb/:kbId` | 文档上传、解析、任务轮询、查看结果 |
| `/` | 引擎任务列表（兼容） |
| `/jobs/:jobId` | 项目/记录/条款/证据/新词 |
| `/dictionary` | 业务词典 |

未登录访问任何业务路由会重定向到 `/login`；401 自动清理令牌。

### 10.5 测试

```powershell
cd apps/api
python -m unittest discover -s tests -q     # 9 个平台测试
cd ../../metal-doc-agent
python -m unittest discover -s tests -q     # 198 个引擎/契约测试
```

平台测试覆盖：未认证 401、登录、知识库、上传幂等、解析、任务、结果产物、预览/页图/版面、新词接受/映射/拒绝与回流、分享令牌、API Key 撤销、审计日志。

### 10.6 P1 预览与 worker（2026-10-27）

| 能力 | 实现 |
|---|---|
| 页图 | PDF OCR 渲染页图到 `pages/page-XXXX.png` |
| 版面块 | OCR 同时写 `pages/layout-XXXX.json`（类型/bbox/置信度/文本/错误） |
| 预览 API | `GET /v1/documents/{id}/preview`、`/pages/{n}/image`、`/pages/{n}/layout` |
| 前端 | `/kb/:kbId/documents/:docId/viewer`：页图 + 版面叠加框 + Markdown/版面块 + 翻页 |
| Worker | `python apps/worker/main.py --watch`（轮询队列）或 `--once`；`HANSON_INLINE_JOBS=0` 关闭请求内执行 |
| 契约 | 页图以 blob 方式带 Bearer 获取，避免无鉴权图片 URL |

`parsekit` 迁移策略：复用其 PP-DocLayoutV3 服务与 PyMuPDF 渲染思路，但产物直接写引擎 `Page.layout_path` 与侧车 JSON，不再迁移旧 Markdown 拼接/header-footer 代码。证据高亮：记录/条款值点击 → 证据卡片 → 预览页按 bbox/引用文本/表格块高亮。

### 10.7 P3 新词复核闭环（2026-10-27）

| 能力 | 实现 |
|---|---|
| 接口 | `POST /v1/documents/{id}/new-terms/review`、`GET /v1/documents/{id}/reviews` |
| 动作 | `accept`（可给出编码/名称/所属大类/标准号）、`map`（映射已有编码并加别名）、`reject` |
| 回流 | 写入 `configs/business_dictionary.local.json`；`JsonDictionaryAdapter` 合并后参与后续匹配；路径可由 `BUSINESS_DICTIONARY_OVERRIDE` 指定，空值禁用（单测只读快照，避免本地回流污染用例） |
| 当前文档 | `reapply_alignment()` 重算 `item_inventory_aligned.json`/`alignment.json`/`new_terms.json`，刷新 `artifacts.json` |
| 复核记录 | `review_events`（文档/类型/原始/动作/编码/操作者/原因）+ 审计日志 |
| 前端 | 结果页新词标签：行内接受/映射/拒绝、确认面板、复核历史；从知识库进入自动带 `documentId` |
| 权限 | 仅用户 JWT 可确认新词；API Key 只读 |
| 一致性 | 进程内 `threading.Lock` 串行化词典写入；单节点部署约定，不跨进程并发写 |

迁移：`apps/api/alembic/versions/541ff3a3dca6_review_events.py`（可 downgrade）。

### 10.8 文档级整体复核与版本（2026-10-27）

| 能力 | 实现 |
|---|---|
| 状态 | `POST /v1/documents/{id}/review`：`draft → review → confirmed`；确认前必须处理完待处理新词 |
| 锁定 | 确认写入 `confirmed_job_id/confirmed_by/confirmed_at`，对应 `document_tasks.locked=true`；锁定后新词操作与任务重试返回 409 |
| 版本 | 确认后重新拆分 `review_version + 1`，新建独立 job（幂等键带版本号），旧任务与产物保留 |
| 前端 | 结果页复核面板（提交/确认/重新拆分）、知识库与预览页版本徽标、锁定任务标记 |
| 迁移 | `c3a9d5e7f1b2_document_review.py`、`e1b2c3d4f5a6_document_task_lock.py`、`f2c3d4e5a6b7_backfill_locked.py` |

### 10.9 A9 任务状态机与 worker 常驻（2026-10-27）

| 能力 | 实现 |
|---|---|
| 状态迁移 | 仅允许 `queued → running → succeeded/review/failed`、`failed/review → queued`；非法迁移抛 `ValueError` |
| 抢占 | 每 job `.runner.lock` 以 `O_EXCL` 创建，跨进程保证同一 job 只被一个 worker 执行 |
| 心跳与回收 | 运行中每 30s 刷新锁；`run_queued` 先回收心跳超过 `--stale-seconds`（默认 300s）或无锁的 `running` 任务 |
| 重试 | `worker --job-id` 对 `failed/review` 自动重置；`succeeded` 拒绝重跑；平台重试接口前置状态检查 |
| 锁定 | 文档确认后对应 `document_tasks.locked=true`；锁定任务重试返回 409，前端隐藏重试按钮 |
| 验证 | 引擎 206 + 平台 11 测试；浏览器 `HANSON_INLINE_JOBS=0` + `--watch`：确认 v3 → 重新拆分 v4 → worker 消费并自动刷新 |

### 10.10 P2 结果页与知识库导航整合（2026-10-27）

| 能力 | 实现 |
|---|---|
| 标准拆分列表 | `/kb/:kbId/extractions`：文档 × 当前任务，拆分/复核状态、版本、项目/记录/新词、更新时间与操作；运行中任务每 2s 轮询 |
| 知识库子导航 | `KbNav`：文档与任务 / 标准拆分 |
| 文档标签 | `apps/web/src/navigation.tsx` 的 `DocumentTabs`：原文预览 / 项目清单 / 记录 / 条款 / 证据 / 新词（带数量）；`?tab=` 为唯一状态，预览页与结果页跨路由互跳 |
| 任务中心 | `/` 改用平台 `GET /v1/tasks`（`kb_id` 可选），返回 `kb_id/document_id/version/locked` 并链接到文档结果与标准拆分 |
| 验证 | 平台 11 + 引擎 206 测试；浏览器走通知识库子导航 → 标准拆分 → 结果标签 → 原文预览 → 返回；Web build 通过 |

### 10.11 P2 结果落库与分享（2026-10-28）

| 能力 | 实现 |
|---|---|
| 结果表 | `document_items`、`document_records`、`document_clauses`、`evidence_index`，按 `document_id + job_id + version` 存储，旧版本保留 |
| 同步 | `ensure_results_synced()` 在结果 GET 首次访问时从 artifacts 重建当前 job 索引；新词复核与任务重试将 `results_job_id` 置空触发重建 |
| 查询 | `GET /documents/{id}/items|records|clauses|evidence` 优先读索引表，产物缺失时回退 artifacts；`GET /alignment`、`POST /results/sync` |
| 分享 | `POST /documents/{id}/share` 生成 15 分钟 HMAC 令牌；`GET /v1/share/{token}` 返回文档/任务/项目/记录/条款/证据；前端 `/share/:token` 只读页 |
| 前端 | 有 `documentId` 时结果页改用文档结果端点；结果页右上“生成分享链接”并复制 |
| 迁移 | `g3d4e5f6a7b8_results_index.py`（文档索引列 + 四张表） |
| 验证 | 平台 12 + 引擎 206 测试；浏览器结果页读取、分享链接、只读标签切换；DB 校验 v4 项目 1/记录 1/条款 0/证据 2 |

### 10.12 P4 安全与依赖收口（2026-10-28）

| 能力 | 实现 |
|---|---|
| 安全测试 | 知识库隔离（非成员 KB/文档/任务/上传 403）、上传文件名穿越、分享令牌过期、只读 API Key 写操作 403、审计日志仅 admin |
| 依赖锁定 | `apps/api/pyproject.toml` 与 `metal-doc-agent/pyproject.toml` 的运行时依赖改为 `==`；Web 由 `pnpm-lock.yaml` 锁定 |
| 清理 | 仓库扫描无旧 RAG/检索/图谱/旧术语集代码；旧 `hansonDoc_RAG` 保持只读远端 |
| 待补 | Docker/三平面容器化、A8/A12 待业务/架构确认；A10 依赖扫描与 A11 前端测试已关闭（见 10.16） |
| 验证 | 平台 15 + 引擎 255 + Web 5 测试；Web build |

### 10.13 1.35 地址切换与真实 PDF 复跑（2026-10-28）

| 能力 | 实现 |
|---|---|
| 地址 | 模型设备 `192.168.1.35`；9977 GLM-OCR、9978 Layout、9989 Qwen3.5-9B |
| Qwen 启动 | GB10 并行 GLM/Layout 时 `32K/0.25` 无 KV cache；改为 `16K / 0.35 / 2 seq` 后 ready |
| 默认模型名 | `GLM_OCR_MODEL` 默认改为服务端名 `GLM-OCR`（原 `glm-ocr` 会 404） |
| 真实复跑 | Q-Du 302 PDF 10 页：GLM-OCR + Layout + Qwen；5 表 / 3 记录 / 59 证据 |
| 证据 bbox | `attach_evidence_bboxes()` 按引用文本匹配版面块、单表页回退表格块；58/59 证据获得 bbox |
| 预览 | `build_preview`/`load_layout` 读取真实页图与版面侧车，第 6 页 18 blocks 且含 table bbox |
| 平台验收 | 真实 PDF 上传解析：项目 8 / 记录 3 / 条款 34 / 证据 59；记录值→证据卡片→第 5 页真实页图高亮 |
| 复核闭环 | 真实 PDF 8 个新词拒绝 → 提交复核 → 确认锁定 v1；任务 locked、重试 409、前端显示已锁定 |

### 10.14 真实 PDF 业务编码确认与词典回流（2026-10-28）

| 能力 | 实现 |
|---|---|
| 业务编码 | v2 拆分的 8 个 pending 新词按业务确认：尺寸→`CATEGORY:68`、形状和尺寸→映射 `CATEGORY:68`、表面质量→`CATEGORY:69`、超声波检测→`CATEGORY:70`、尺寸偏差→`DIM:DEV`（归 `CATEGORY:68`）、`GB/T 228`→映射 `TENS_RT:2362`（别名为“GB/T 228”）、`GB/T 3246.2`→`MICRO:3246.2`；表头符号 `E` 拒绝；其中 `DIM:DEV` 后因表 5 误配在 v4 停用（见 10.15），`E` 在 v8 按“弹性模量(E)”确认 `TENS_RT:E` |
| 回流 | `configs/business_dictionary.local.json` 新增 5 条并更新 `TENS_RT:2362` 别名；`JsonDictionaryAdapter` 合并后参与后续匹配 |
| 对齐结果 | 大类 8/8（100%）、方法 4/4（100%）、检测项目 4 命中 + 1 ambiguous（Rp0.2）+ 1 拒绝（E）；pending 0 |
| 复核 | 提交 → 确认 v2 锁定；v1/v2 任务均 `locked`；重复确认/确认后新词/锁定任务重试均 409 |
| 落库 | `POST /results/sync`：v2 项目 8 / 记录 3 / 条款 34 / 证据 59，`results_job_id=8633af7f0898` |
| 记录 | `review_events` 保留 v1 拒绝与 v2 正式确认两轮决策；审计日志含 `new_term.*`、`document.review.*`、`document.results.sync` |
| Rp0.2 裁决 | 快照内 `TENS_RT:RP0.2`（规定塑性延伸强度）与 `TENS_RT:RP0.2#1`（规定非比例延伸强度，重复导入）同符号导致 ambiguous；裁决 `TENS_RT:RP0.2` 为规范编码，`#1` 在 override 置 `inactive`，其“规定非比例延伸强度”与英文名并入 `TENS_RT:RP0.2` 别名；v3 重跑 `Rp0.2 → TENS_RT:RP0.2`，检测项目 5/6 命中、ambiguous 0，v3 确认锁定并落库 |

### 10.15 外部 schema 投影（M2 准备，2026-10-28）

| 能力 | 实现 |
|---|---|
| 目标 schema | 从 hansonDoc_RAG `产品标准抽取模板`（3 类 27 字段）整理为 `configs/schema_templates/product_standard.json`：检测项目 13 字段、标准信息 2 字段、热处理制度 12 字段 |
| 投影 | `metal_doc_agent/schema_projection.py`：项目清单 × 记录 × 检验项目 × 条款 → schema 行；字段为空即记为缺口，不臆造；校验 `required_missing`、`type_mismatch` |
| CLI | `python -m metal_doc_agent.cli schema project --job <job_dir> --template <json> --out <file>` |
| 真实结果（Q-Du 302 v8） | 20 行；字段 208/262（79.4%）、条件必填 74/74（100%）；标准名称/编号 2/2；错误 0 |
| 字段覆盖 | 项目名称/材料牌号/标准要求/位置/取样说明/锻件类型 100%；试验方法 90%；单位/试验温度/方向/试样状态 75%；取样数量 40%（多类别留空）；尺寸厚度 0% |
| 误配修复 | v3 发现表 5（工艺参数偏差记录）被候选配方误绑为“尺寸偏差”；v4 增加工艺参数表识别（整表 unmapped），`DIM:DEV` 置 inactive，重新拆分确认后项目 8→7、投影 21→20 行 |
| P2 修复 | 条款 67 条（补齐 4.8.1、4.9.1、5.2.2、5.2.3.3–.5、5.2.4.3、5.2.6.6、6.2；5.2.6.7 正文归还 5.2.6.6；重复 id 合并）；按表 3 方法章节回填 item 方法，超声波检测绑定 `NDT:6519`（GB/T 6519-2013）；v7 落库成功（条款 67/证据 75） |
| P3 修复 | 单位 `required_when=numeric`（定性项允许空）；多类别取样数量留空并保留明细；项目名称去单位；`E`→`TENS_RT:E`（弹性模量）；热处理制度无参数时 `applicable=false`；v8 确认锁定、错误 0 |
| 正确性核对 | T1/T2/T3 与原文逐项一致；T5 误配、条款正文缺口、超声方法未绑定等详见 `metal-doc-agent/eval/schema/product_standard/verification-q-du-302-v3.md` |
| 第二标准验证 | GB/T 1591-2018（22 页 / 15 表 / 519 记录）同一模板投影 1236 行：字段 70.3%、条件必填 100%、校验错误 0、试验方法 100%、方向 16.3%、尺寸厚度 19.6%、试验温度 18.1%；冲击 202 条 KV2（5 温度 × 2 方向）、碳当量 221 条、Pcm 28 条，`弯曲试验`/`尺寸` 不再串属性；详见 `metal-doc-agent/eval/schema/product_standard/stability-gbt1591.md` |
| 矩阵抽取 | `extraction/matrix.py`：按绑定列确定性组装条件矩阵（冲击“温度 × 方向” → KV2，碳当量按厚度区间 → CEV/Pcm）；牌号脚注字母剥离、质量等级列表展开；pipeline 对条件矩阵按表替换记录，对无温度/方向的单列测度（如单个 KV2 列）并入同牌号行，避免 Rm/A/Z 等被丢 |
| 表头映射优先级 | Qwen 整表映射偏移时（例：Q-Du 表 2 属性列整体右移一列）不再覆盖规则已识别的列；仅 `A50mm/ReH/KIC` 允许模型细化，模型只补规则缺口 |
| 基线回归 | 20 份 goldset 重跑：记录 F1 0.8733、字段 F1 0.832、数值 0.9347、覆盖 0.85；修复前 0.8037/0.7464/0.8903/0.825；Q-Du 302、GJB 3325A/5301、GB/T 33084 的串列/丢字段恢复，无单文档下降超 0.05 |
| 硬表修复 | `configs/table_repairs.json` 新增 `GBT15912018/T4`：按 PDF 第 10 页重建 16 列 × 16 条化学成分数据（Q355N B–F、Q390N B–E、Q420N B–E、Q460N C–E），消除跨页 rowspan 溢出导致的 `CQ390N` 等 4 条污染记录；`Als` 列由 `_element_tokens` 的 `canonical_element` 兜底识别为 Al |
| 定性项目规则 | 新增 `configs/qualitative_requirements.json`：按标准编号 + 项目关键词映射条款号；投影时 `材料牌号=全部牌号`、`标准要求` 取条款正文（含标题兜底），GB/T 1591 的弯曲/厚度方向/外形/尺寸/无损/表面 12 个必填错误清零 |
| 表 13 方法绑定 | `取样部位及方法` 归为取样位置（condition）、`试验方法` 归为 method；`_clean_method` 保留“双方协商/相应精度的量具/目视及测量”等短文本并拒绝“见X.Y”引用；`_clause_ref` 把“见8.2”归一化为条款号后取方法（GB/T 4336）；投影试验方法覆盖 1236/1236（100%） |
| 已知缺口 | 热处理制度无参数（`applicable=false`）；定性项目规则为模板约定，不代表源表存在对应数值 |
| 测试 | 新增 `tests/test_schema_projection.py` 8 个、矩阵抽取 3 个、CEV 绑定 1 个、属性族隔离 1 个、方法列角色 1 个、项目方法文本 1 个、工艺参数表绑定 1 个、条款正文/去重/方法绑定 5 个、表头脚注/合并单元/T4 对齐 4 个、元素脚注/Als 回归 2 个、矩阵合并 2 个、表头映射防漂移 1 个、M2 数据集 3 个、条款结构/方向 4 个、就绪检查 3 个、蒸馏 3 个；引擎 255 通过 |

### 10.16 A10 依赖扫描 / A11 前端测试（2026-10-28）

| 能力 | 实现 |
|---|---|
| 依赖扫描 | `pip-audit 2.10.1` 分别扫描引擎（28 个解析依赖）与 API（21 个）；修复前引擎 76 条（lxml 2 / pillow 74）、API 22 条（PyJWT） |
| 升级 | `lxml==6.1.3`、`pillow==13.0.0`（engine dev/models）、`PyJWT==2.15.1`（api）；升级后两项扫描均 “No known vulnerabilities found” |
| 许可证 | MIT：pydantic/fastapi/PyYAML/sqlalchemy/alembic/PyJWT；BSD-3：lxml/httpx/uvicorn/pypdf；Apache-2.0：python-multipart/bcrypt；MIT-CMU：pillow；PyMuPDF 为 AGPL-3.0（元数据未声明，需业务/法务确认分发方式） |
| 回归 | 升级后引擎 255、平台 15 测试通过；前端 5 测试通过 |
| 前端测试 | `apps/web` 接入 Vitest + jsdom + Testing Library；`pnpm --filter @hanson/web test` 覆盖 StatusBadge（已知/未知）、ErrorNote、EmptyNote、Section、Metric；`typecheck` 通过 |
| 主链路 E2E | `e2e/run_main_flow.ps1`（`pnpm e2e`）：隔离 SQLite + mock OCR/抽取，启动 API/Web 后用 Playwright Chromium 走登录 → 建知识库 → 上传 → 解析 → 记录 → 退出；1 个用例通过 |

### 10.17 M2.1 样本增强（2026-10-28）

| 能力 | 实现 |
|---|---|
| 扰动词表 | `build_m2_dataset.py`：数字空格、全角数字、牌号脚注、表头别名；只改输入表层，金标输出不变，`meta.ops` 记录 from/to 便于追溯 |
| 扰动范围 | 仅 train/dev 生成 185 条；heldout 不扰动，保持评测干净 |
| 引用约束 | 从 `references.json` 生成 383 条：输入含预算、排序、已选数与重复标记，输出 `expand` + `selection_reason`（selected 141 / budget_exceeded 242） |
| 样本总量 | train 111 / dev 581 / heldout 110；基础 29/162/43，其余为增强 |
| 就绪检查 | `tools/m2_readiness.py` → `eval/m2/readiness.md`：泄漏、同族切分、heldout 纯度、可追溯均通过；heldout 文档类型 3/4 为 warn；M2.2 完成 |
| 测试 | `tests/test_m2_dataset.py` 7 个 + `tests/test_m2_readiness.py` 3 个 |

### 10.18 条款抽取结构修复（2026-10-28）

| 能力 | 实现 |
|---|---|
| 列表项误判 | OCR 的“1 类件应每批……”原被当成一级标题，正文被挂到条款 1；`_heading_is_valid` 对裸数字标题拒绝含句读或超长文本 |
| 行内正文 | “5. 2.3.4.1 在…切取1个试样。”整句被当标题；`_split_inline_title` 把含句号的标题转为正文 |
| 取样字段 | 新增 `在…切取/取样` 位置与 `切取 N 个` 数量抽取；`温度` 字段改为金标同名的 `test_temperature` |
| 方向字段 | 新增纵向/横向/弦向/径向/切向/轴向与“横向（弦向）”成对写法识别；多个方向并存时不臆断 |
| 效果 | 条款字段缺失 112→103、字段命中 13→23、条款命中 11→12；总错误 493→483；记录与 schema 投影指标不变（Q-Du 20 行/79.4%、GB/T 1591 1236 行/70.3%，错误 0） |
| 回归 | `tests/test_clauses.py` 新增 4 个；引擎 249 通过 |

### 10.19 M2.2 教师蒸馏（2026-10-28）

| 能力 | 实现 |
|---|---|
| 教师选择 | 当前 IDE Agent（DeepSeek-V4.1-Flash）离线生成，不新增模型服务；输入输出分离，教师只看 `input` |
| 难例选择 | `tools/build_teacher_set.py emit`：按 eval 错误数取 dev Top5 文档，每篇表头/记录/条款各 1 条，共 15 条 |
| 教师输出 | `validate`：L0 证据过滤（值必须逐字出现在输入行/条款原文），15/15 接受、0 丢弃；字段一致 87.8%（表头 95%、记录 82.8%、条款 60%），整条一致 46.7% |
| 数据版本 | `data/m2/teacher-v1/`：`teacher_inputs/gold/raw/teacher` + `report.json` + `prompt.md`；teacher 占 1.87%，金标优先 |
| 主要差异 | 金标自定义键、旧牌号/统一数字代号列角色、`grade/condition` 命名；作为 M2.3 训练目标词表 |
| 回归 | `tests/test_teacher_set.py` 3 个；引擎 255 通过 |

### 10.20 M2.3 LoRA 训练（2026-10-29）

| 能力 | 实现 |
|---|---|
| SFT 数据 | `tools/prepare_sft.py` → `data/m2/sft-v1/`：train 692 / eval 110（chat messages）；任务分布 header 20、row 107、perturb 185、clause 64、citation 316；token p50 219 / p99 1064 / max 1481 |
| 训练脚本 | `training/m2_lora/train_lora.py`：完整 `apply_chat_template` 后按 prompt 前缀把 label 置 -100，只训练 assistant JSON；新增 `--save-steps` / `--resume` 便于断点续跑 |
| 首次事故 | 2026-10-28 batch 4 / max_seq 2048 跑到第 3 步（32s/步）后 1.35 整机硬挂，23:39 重启；内核日志无 OOM 记录，推断统一内存耗尽；`device_map="auto"` 曾导致参数 offload 到 disk，已改为 `model.to("cuda")` |
| 保守重跑 | `training/m2_lora/run_m2_lora.sh`：batch 1 / grad_accum 16（等效 16）/ max_seq 1280 / lr 1e-4 cosine / 2 epoch / bf16 / gradient checkpointing；tmux 会话 `m2train`，内置内存看门狗写 `logs/mem.log` |
| 结果 | 88 步、1701s（约 20s/步）；train_loss 0.0611；eval_loss 0.0678（epoch1）→ 0.0695（epoch2）；峰值期间可用内存稳定 76GB、swap 未动用 |
| 产物 | `/home/grainuser/hanson_m2/adapter-v1`：`adapter_model.safetensors` 116MB（SHA256 `d97807a4…`）、`run_report.json`、`checkpoint-80/88`；登记见 `metal-standard-agent-plan/model-registry.md` 2.1 |
| 环境限制 | GB10 为 aarch64 + CUDA 13，`causal_conv1d` / `flash-linear-attention` 未安装，Qwen3.5 线性注意力走 PyTorch 参考实现，长序列显存开销被放大 |
| 冒烟验证 | eval 第 1 条（header_mapping）对比同 prompt：base 输出自有 `header_mapping` 词表、非法 JSON；adapter 在 `enable_thinking=False` 下输出金标 `columns` schema 合法 JSON（691 字符）；`enable_thinking=True` 时仍走推理、不落 JSON |
| 推理约束 | 使用 adapter 必须显式 `chat_template_kwargs.enable_thinking=false`，与现有 9989 服务一致；guided JSON 解码已完成（见 10.21） |
| 待办 | 两阶段抽取、推理参数固化、管线级 heldout 评测 |

### 10.21 heldout 基线与 guided JSON（2026-10-29）

| 能力 | 实现 |
|---|---|
| 评测脚本 | `training/m2_lora/eval_heldout.py`：base 与 adapter 用同一 prompt 各跑一遍，greedy、`enable_thinking=false`、`max_new_tokens=512`，逐样本写入报告 |
| 指标 | JSON 合法率、整条 exact、字段级 P/R/F1（叶子 `path=value`）、无证据率（只查 `*.raw`，跳过 role/unit 等结构字段） |
| 结果 | 110 条 heldout SFT 样本：base 合法 0.9636 / exact 0 / F1 0.179 / 无证据 0.68%；adapter 合法 1.0 / exact 0.618 / F1 0.782 / 无证据 0.92% |
| 分任务 | citation_constraint 67 条 adapter 全对；row_record F1 0.870、header_mapping 0.781、clause_extract 0.096（金标自定义键仍是短板，与教师条款一致率 60% 相符） |
| guided JSON | lm-format-enforcer 前缀约束 + 每任务 JSON Schema；24 条上非法 JSON 0、exact 12/24、F1 0.7868，输出与未约束逐字一致；延迟 52.5s/条 vs 约 7s/条（7.5×），默认关闭，只作 schema 安全网 |
| 兼容垫片 | transformers 5.20 不再暴露 `transformers.tokenization_utils.PreTrainedTokenizerBase`，lmf 仍按旧路径导入；脚本在 `sys.modules` 注入别名后可用 |
| 产物 | `metal-doc-agent/eval/m2/heldout-lora.json`、`heldout-guided.json` |
| 局限 | 样本级评测，不等于管线级 heldout；M2.4-01/03 的正式口径（对 5 份 heldout 文档跑整条流水线）待做 |

### 10.22 两阶段抽取与长表稳定性（2026-10-29）

| 能力 | 实现 |
|---|---|
| 两阶段脚本 | `training/m2_lora/eval_two_stage.py`：阶段 1 只给 `header_paths + sample_rows` 预测 mapping；阶段 2 把预测 mapping（非金标）拼进 row_record 输入，测的是误差传播 |
| 两阶段结果 | 7 表 13 行：mapping 角色准确率 0.874、三元组全对 0.573；JSON 合法 1.0、行 F1 0.642；同批单阶段（金标 mapping）行 F1 0.870 |
| 掉分归因 | 列角色大多正确，错误集中在属性名与单位（金标自定义键），qs10 两份老企业标准最差（全对 0.000/0.286） |
| 长表稳定性 | GB/T 14992 表 2（T8，20 行）：20/20 行产出记录、JSON 合法 1.0、0 失败、属性键集合完全一致（12 个）、约 30s/行；mapping 13/16 列（尾部空列被丢弃） |
| 数据问题 | T8 artifact 由两个分页块拼接，夹了两行重复表头（`新牌号|原牌号`）并重复 8 行数据，导致 6 条重复牌号与 1 条 grade=新牌号；正式管线需在阶段 2 前过滤表头行/重复块 |
| 主机变更 | 2026-10-29 模型设备 IP 改为 `192.168.188.75`，重启后 `adapter-v1` 与数据保留；中途一次两阶段任务因重启中断，已拆分重跑 |
| 产物 | `metal-doc-agent/eval/m2/two-stage.json`、`longtable-t8.json` |

### 10.23 推理参数固化与稳定性（2026-10-29）

| 能力 | 实现 |
|---|---|
| 参数文件 | `training/m2_lora/inference_params.json`（`lora-infer-v1`）：`enable_thinking=false`、`do_sample=false`（贪心）、temperature/top_p 为空、repetition_penalty 1.0、max_new_tokens 512、seed 0 |
| 稳定性脚本 | `training/m2_lora/eval_stability.py`：4 类任务各 1 条 + 1 条额外 row_record，各生成 3 次，比较输出 sha256、JSON 合法率与是否触顶 |
| 结果 | 15 次生成全部逐字一致（deterministic true）、JSON 合法 1.0、截断 0；最大输出 302 token（上限 512，余量约 210）；耗时 256.5s（含加载） |
| 结论 | 贪心 + 关闭思考在固定参数下可复现，max_new_tokens 512 足够；后续管线级评测复用同一套参数 |
| 产物 | `metal-doc-agent/eval/m2/stability.json` |

### 10.24 旁路 adapter 服务与管线级 A/B（2026-10-29）

| 能力 | 实现 |
|---|---|
| 旁路服务 | `training/m2_lora/serve_adapter.py`（FastAPI + transformers + peft）监听 9990：`/health`、`/v1/models`、`/v1/chat/completions`；固定 greedy / 无思考 / 512 token，请求里的采样参数一律忽略以保证可复现 |
| 部署 | 主机 `192.168.188.75`：`nohup python code/serve_adapter.py --model ... --adapter ... --params code/inference_params.json --port 9990`；与 9977/9978/9989 并存，不改生产服务 |
| 管线 A/B | 5 份 heldout 文档走完整管线（OCR mock 走 markdown 解析 + qwen 抽取），输出 `runs/m2_lora_adapter/<doc>`，再用 `metal-doc eval` 评分；基线取 `runs/m2_baseline` 同 5 份文档 |
| 结果 | record 0.800 = 0.800；field 0.744 vs 0.7555（−0.0115）；value 0.7768 vs 0.7778；clause 0.100 持平；coverage 0.700 持平；evidence 1.000；幻觉率 0.000 |
| 归因 | 引擎 prompt（含 allowed_properties/sample_rows）与 SFT prompt 不同分布，LoRA 仅 0.32% 参数，OOD prompt 下近似退化为 base；管线级收益需引擎切到 SFT 两阶段 prompt |
| 环境问题 | 9989 base Qwen 一开始 `Engine core initialization failed`（KV 预算不足，见 10.25）；调整启动顺序后 9989 恢复，A/B 仍使用历史基线 run |
| 产物 | `metal-doc-agent/eval/m2/pipeline-lora-5docs.json`、`runs/m2_lora_adapter/` |

### 10.25 9989/9990 启动顺序与显存预算（2026-10-29）

| 项 | 结论 |
|---|---|
| 现象 | 9989 启动失败，日志末尾为 `RuntimeError: Engine core initialization failed`，前序为 `ValueError: No available memory for the cache blocks` |
| 根因 | 9990 旁路先起已占约 20GB；vLLM `--gpu-memory-utilization 0.35`≈41.6GB，扣掉 19GB 权重后不足以分 KV，直接判定无 cache 空间 |
| 验证 | 停 9990 → 9989 起（约 3 分钟 ready）→ 再起 9990，两服务共存：占用 98GB/119GB、可用约 20GB |
| 规则 | 必须 9989 → 9990 顺序启动；不要再叠加第三个 9B 实例；重启机器后按 9977 → 9978 → 9989 → 9990 顺序拉起 |
| 相关 | `start_qwen35_9b.sh` 未改动；旁路启动命令见 `model-registry.md` 3 节 |

### 10.26 引擎 SFT prompt 切换实施（2026-10-29）

| 项 | 实现 |
|---|---|
| 提示单一来源 | 新增 `extraction/sft_prompts.py`；`tools/prepare_sft.py` 改为引用同一常量，训练/推理文本无法漂移 |
| 开关 | `Settings.extractor_prompt_style`（env `METAL_DOC_EXTRACTOR_PROMPT`，默认 `native`）+ `sft_max_tokens` 512 / `sft_row_limit` 30 |
| 表头阶段 | `QwenExtractor._ask_mapping_sft`：只发 `header_paths + sample_rows`，`columns` 解析后与规则映射合并，规则已识别列不被覆盖 |
| 行阶段 | `_ask_row_sft`：逐行调用，值必须逐字命中该行单元格；`_sft_row_candidates` 只接受规范属性且要求唯一列匹配；`_sft_grade_is_acceptable` 拒绝落在条件列的 grade（如 T6） |
| 行过滤 | `_duplicate_row_indexes` 过滤重复表头行与跨分页重复块（T8 场景），计数 `rows_dropped` |
| 回退 | 行阶段 JSON 非法/空 → 回退规则组装，计数 `row_fallbacks`；超过 `sft_row_limit` 的表整体跳过 SFT 行调用 |
| 三路 A/B | base+native 0.7555 / adapter+native 0.7440 / adapter+sft_m2 0.6909 / base+sft_m2 0.7245（field F1，5 份 heldout） |
| 归因 | 首次无校验实现 record 0.433、field 0.486；收紧后 record 0.8、field 0.6909；回归集中在 mas7079_b；base+sft_m2 也掉 0.03，说明 prompt 缺 `allowed_properties` 是主因 |
| 结论 | 未达门槛（field ≥0.7555、header ≤73），默认保持 native，`sft_m2` 仅实验开关 |
| 测试 | 新增 `tests/test_sft_prompts.py`（3）、`tests/test_qwen_sft.py`（8）；引擎 266 通过 |

### 10.27 SFT v2 约束数据与 adapter-v2（2026-10-29）

| 项 | 实现 |
|---|---|
| 根因 | 10.26 的掉分一半来自 prompt 缺 `allowed_properties`/`profile`（`base + sft_m2` 也掉 0.03），因此补约束样本重训 |
| 数据 | `tools/build_sft_v2.py` → `data/m2/sft-v2/`：表头任务 `header_mapping_constrained`，payload 增加 caption/profile/orientation/n_cols/allowed_properties/allowed_elements；金标属性映射到 engine 词表，未知表头属性→`ignore`（train 8 / eval 4）、未知行属性丢弃（train 102 / eval 4） |
| 提示 | `sft_prompts.INSTRUCTIONS` 新增 constrained 指令；`qwen.py::_ask_mapping_sft` 同步发送约束字段 |
| 训练 | `run_m2_lora.sh` 支持 `DATA_DIR`/`OUTPUT`/`MAX_SEQ`；`adapter-v2` 88 步 1725s，train_loss 0.0592，eval_loss 0.0739，max_seq 1536 |
| 服务 | 9990 切换 `adapter-v2`；`serve_adapter.py` 按 adapter 路径生成 model id，`/health` 返回真实 adapter 名 |
| 管线结果 | `adapter-v2 + sft_m2` field 0.7440 / record 0.800 / value 0.7768 / header 75 / fp-fn 3-8，与 `adapter-v1 + native` 逐文档一致；相对旧 sft_m2（0.6909）收回 +0.0531 |
| 结论 | prompt 缺口关闭，但相对 base+native（0.7555）仍差 0.0115，门槛未达，`sft_m2` 保持实验开关 |
| 测试 | 新增 `tests/test_sft_v2.py`；引擎 268 通过 |
| 产物 | `metal-doc-agent/eval/m2/sft-v2-5docs.json`、`training/m2_lora/adapter-v2-run-report.json` |

### 10.28 映射投票与内存事故（2026-10-29）

| 项 | 实现 |
|---|---|
| 开关 | `METAL_DOC_EXTRACTOR_PROMPT=vote`；native 走 `QWEN_BASE_URL`（9989 base），约束 SFT 走 `SFT_BASE_URL`/`SFT_MODEL`（9990 adapter-v2） |
| 投票 | `qwen.py::_vote_columns`：规则识别列优先 → 两路一致采用 → 冲突按规范属性得分（property>grade/condition>ignore）→ 同分取 native；grade 索引不一致时两路 grade 作废回退规则 |
| 行阶段 | 投票只影响表头，行仍规则组装，避免逐行调用放大延迟 |
| 结果 | field 0.7555 / record 0.800 / value 0.7778 / header 73 / fp-fn 2-7，与 base+native 逐文档一致，无增益也无回归 |
| 测试 | 新增 3 个投票用例（一致、冲突取规范/native、grade 分歧回退），引擎 271 通过 |
| 内存事故 | 9990 被重复启动（两次 nohup）→ 9989+双 9990+OCR 使内存 119/119、swap 15/15、load 94，SSH banner 超时；停止 OCR 释放约 19GB 后恢复，服务全程 HTTP 可用 |
| 规则 | 9990 单实例；启动后用 `ps -eo pid,args | grep serve_adapter` 校验；离线评测期间可停 OCR（管线走 markdown 不需要 OCR） |
| 产物 | `metal-doc-agent/eval/m2/vote-5docs.json`、`runs/m2_vote/` |

### 10.29 M2 收口与 M2.5.1 配方契约（2026-10-29）

| 项 | 实现 |
|---|---|
| M2 收口 | 两条改造路径走完：约束重训 `sft_m2` 0.7440（与 native+adapter 逐文档一致）、映射投票 `vote` 0.7555（与 base+native 逐文档一致）；G2 的 95% 目标未达，剩余 73 条 header 错误属 native 映射本身，移交 M2.5 |
| 配方 schema | `schemas/recipe.schema.json` + `metal_doc_agent/recipes/schema.py`：draft 2020-12，校验 6 个 active 与 1 个 candidate 配方，`recipe_id` 与文件名一致 |
| 结构签名 | `RecipeSignature` 增加 `multi_header` / `unit_set`；`build_signature` 从 `header_rows>1` 与表 units 生成 |
| 绑定覆盖 | `tools/recipe_coverage.py` → `eval/recipes/binding-coverage.json`：257 张表，1862/1916 列绑定（0.9718），文档级 candidate 命中 20/20，exact 0 |
| Novelty | 表级 unknown 87（33.9%）：classification 46 + unknown profile 41，无对应配方；高于 20% 目标，进入 M2.5.2/2.5.4 冷启动 |
| 阈值结论 | `signature_score` 在列数/块数/token 不严格一致时上限约 0.85，0.9 exact 门槛不可达；M2.5.2 需重标定阈值或改为「同族签名 + 人工签字」 |
| 测试 | 新增 `tests/test_recipe_schema.py` 5 个；引擎 276 通过 |

### 10.30 M2.5.2 检索与路由（2026-10-29）

| 项 | 实现 |
|---|---|
| Router | `metal_doc_agent/recipes/routing.py`：`decide_route(table, recipes, history=None, force_human=False)` 输出 queue/status/recipe_id/score/confidence/reasons；`doc_queue` 按 production > human > explore 归并 |
| 排序 | `rank = 0.9 * signature_score + 0.1 * token_overlap`；纯签名分下 mechanical 族内硬度/力学两配方差 0.009，加 token 重叠后歧义消除 |
| 阈值 | production 0.75 / exact 0.85 / explore 0.60；top2 rank 差 ≤0.05 进 human（ambiguous_top2）；列数 >40 或块数 >2 进 human（risky_table_size） |
| 三队列 | `metal_doc_agent/queues/store.py`：`QueueStore` 三条 JSONL lane + threading.Lock，enqueue/dequeue/peek/list/stats + `fallback_to_explore`（生产失败不阻塞） |
| 评测 | `tools/route_eval.py` → `eval/recipes/routing.json`：20 份 / 257 表，production 49、explore 177、human 31；文档级 production 17/20 = 0.85 |
| Novelty | 0.3385，仍高于 <20% 目标：no_recipe 87（classification 46 + unknown 41）、low_confidence 121；归入 M2.5.4 冷启动 |
| human 归因 | 31 条中 mechanical 28，几乎全是 ambiguous_top2（同族配方签名接近），属标定问题；阈值先固定 0.75，待影子成功率再接 history |
| 未接入 | Router 未接 pipeline/api，三队列未实际投递，history 参数为空；M2.5.3 统一落地 |
| 测试 | 新增 `tests/test_routing.py` 9 个；引擎 285 通过 |

### 10.31 M2.5.3 生命周期、影子与三队列投递（2026-10-29）

| 项 | 实现 |
|---|---|
| 生命周期 | `recipes/lifecycle.py`：L0–L5 状态机 + `RecipeRegistry`（`configs/recipes/registry.json`）；`load_recipes` 用注册表覆盖 status，晋升/回滚不改配方文件 |
| 迁移与闸门 | L2 需 gold_samples≥3 且 header_mapping≥0.98；L3 需 agreement≥0.98、coverage≥0.95、orphan_rate≤0.01；L4 需 approved_by+approval_note；非法迁移抛 LifecycleError，force 记录 forced=true |
| 回滚/弃用 | rollback 默认撤销最近一次仍生效的晋升（跳过 rollback 记录），支持 --to；deprecate 走 L5，L5→L4 可复活；历史全保留 |
| 影子运行 | `recipes/shadow.py`：同族表重放候选绑定 vs active/规则绑定，统计 matched/drifted/orphaned/extra，可选金标一致率；`tools/shadow_run.py` 出报告 |
| 影子结果 | candidate_mechanical_properties_66a957cb：17 文档 / 55 表，agreement 1.0、coverage 1.0、orphan 0、gold 1.0，passed；与 mechanical_properties_v1 重复，未晋升 |
| 队列投递 | pipeline 新增 `recipe_routing`（METAL_DOC_RECIPE_ROUTING=1）：逐表 decide_route → doc_queue → data/queues/<lane>.jsonl，写 routing.json；入队失败只告警 |
| history | `RecipeRegistry.success_rates()` 供路由使用；影子 --record 回写 stats |
| CLI | `tools/recipe_lifecycle.py`：levels / promote / rollback / deprecate |
| 测试 | 新增 lifecycle 13、shadow 5、pipeline 路由 1；引擎 304 通过 |
| 产物 | `configs/recipes/registry.json`、`eval/recipes/shadow-candidate_mechanical_properties_66a957cb.json` |

### 10.32 M2.5.4 冷启动运营（2026-10-29）

| 项 | 实现 |
|---|---|
| 长尾聚类 | `recipes/coldstart.py`：非 T1 表按 0.7*Jaccard + 0.2*列数近似 + 0.1*方向 贪心聚类（阈值 0.6），输出代表文档/表与建议配方 |
| T1/T2/T3 | T1=生产命中 49；T2=同表型已有 active 配方、需参数化 121；T3=无配方族 87（classification 46 + unknown 41） |
| 聚类结果 | 208 张长尾表 → 130 簇（28 簇多表、102 单表）；最大簇 chemical 9 表/2 文档，代表 gbt14992_2015/T8 |
| dashboard | `tools/coldstart_report.py` → `eval/coldstart.json` + `eval/coldstart.md`：hit 0.8500 OK、novelty 0.3385 GAP、T3 0.3385 GAP（目标 <5%），含 backlog/conversion |
| 探索→配方 | T2 参数化 + shadow，T3 离线 authoring；每簇代表表可作金样例起点；沙箱沿用 tools/recipe_authoring.py，不接入 pipeline/api |
| 运营节奏 | 周跑报告+清队列；月复盘 T2/T3 进度与 G2.5 指标（owner：配方运营/领域专家） |
| 测试 | 新增 tests/test_coldstart.py 9 个；引擎 313 通过 |
| 产物 | eval/coldstart.json、eval/coldstart.md |

### 10.33 M3 Agent 编排骨架（2026-10-29）

| 项 | 实现 |
|---|---|
| 图引擎 | metal_doc_agent/orchestration/graph.py：无 LangGraph 依赖的等价引擎（声明式节点/条件边、步数上限、节点级 checkpoint）；主干 plan→extract→ocr_gate→route→validate→coverage→assemble→publish_gate→publish/human |
| 状态 | state.py：Budget/RetryCounters/RouteInfo/CostUsage/StepRecord/OrchestrationState；m3_state.json 可回读 |
| 工具沙箱 | tools.py：load_artifact/run_extract/validate/retrieve_reference/write_artifact 白名单、路径守卫、超时；无 eval/exec |
| 修复 | repair.py：OCR 低质量→重 OCR、证据/取值错误→重抽、覆盖缺失→人工、预算耗尽→人工；预算测试无死循环 |
| 上下文 | context.py：≤24K 装配；压缩只压条款正文，证据/表头/单位/条款 id 保留；回读无损 |
| 断点/人工 | 每节点落盘；resume_orchestration(decision=publish)；API POST /v1/jobs/{id}/resume |
| 批量 API | batches.py + POST/GET /v1/batches；路径或 job_id、状态聚合、幂等键回放 |
| runner | METAL_DOC_ORCHESTRATE=1 时 job 走图；published→succeeded、review/human→review、failed→failed |
| 评测 | eval/m3.json：3 文档 STP 0.3333、p95 654ms；eval/m3-repair.json 注入首抽失败修复 2/2 |
| G3 | 未通过：STP 0.333<0.80；修复/幂等/断点/成本通过；压缩抽取级回归未测 |
| 测试 | 新增 orchestration 15 + batches 4；引擎 332 通过 |

### 10.34 M4 人机协同（2026-10-29）

| 项 | 实现 |
|---|---|
| 工作台 | apps/web JobDetailPage 新增「字段复核」tab：风险排序、accept/edit/reject、机器 vs 人工 diff、事件列表、批量接受低风险 |
| 事件模型 | metal_doc_agent/review/events.py：ReviewEvent 校验（edit 带新值、edit/reject 带理由）；FeedbackStore 仅收带理由变更，写 data/feedback/feedback.jsonl |
| 复核 API | apps/api：field_review_events 表 + 迁移 h4e5f6a7b8c9；GET/POST /field-reviews、/field-reviews/batch、/field-diff、/review-risks |
| 结果叠加 | /result、/records、分享包按最新事件覆盖机器值；reject 标记 reviewed/reject_reason |
| 高风险闸门 | confirm 前 high 风险字段必须有事件，否则 409 high_risk_fields_unreviewed |
| 风险/审计 | review/risk.py（high=结构缺陷、medium=comparator/缺单位）、review/silent.py（5 类 silent 规则）；tools/review_audit.py 出 20 份 0 silent + 复核队列 |
| 指标 | first-pass 代理 1.0、human_minutes 未测；主动学习队列 high×3+medium |
| 测试 | 引擎 review 11；platform 18；web typecheck + vitest 5 |
| 产物 | eval/m4.json、eval/m4.md |

### 10.35 M5 生产化交付（2026-10-29）

| 项 | 实现 |
|---|---|
| 容器 | infra/docker：Dockerfile.engine/api/web + nginx + compose（postgres/redis/minio/三平面/worker 池） |
| K8s | infra/k8s：namespace/config/PVC、engine-api、worker-prod/explore/human、platform-api、web、Service/Ingress/HPA/PDB/NetworkPolicy；canary overlay |
| GPU 池 | 模型平面仍 1.35；model-plane/README 定义 ocr/extract 池、污点与 9989→9990 顺序 |
| 可观测 | 引擎 /metrics+/ready；平台 /platform/metrics+/platform/ready；Prometheus 告警规则 + Grafana 看板 |
| 备份 | backup.sh/restore.sh/drill.md：pg_dump、数据卷 tar、mc mirror、校验和；未实际演练 |
| 安全 | docs/security.md + check_secrets.py（扫描通过） |
| 运维 | docs/runbook.md、docs/slo.md（SLI/SLO/错误预算/容量/成本） |
| 标准族 | eval/m5.json：五族可运行，绑定率 0.965–0.992；证据率 1.0；silent 0；p95 175.1s |
| 成本 | tools/cost_report.py → eval/m5-cost.json：372 页、1618 CPU 秒、中位 4.3s/页、p95 8.4s/页；单价未定 |
| 测试 | 引擎 test_m5_infra 11（共 354）；平台 19；web 5 |
| G5 | 未通过：无生产 SLA、无演练、无外部安全评审、无试点验收 |

### 10.36 M5 收口与试点验收包（2026-10-29）

| 项 | 实现 |
|---|---|
| 并发压测 | tools/loadtest.py：8 文档/并发 4，p95 1.9s、失败 0、吞吐 2.46 docs/s（mock） |
| 本地备份演练 | infra/backup/drill.py：SQLite+数据卷备份/恢复，文档数/文件/SHA256 全匹配 PASS；非 Postgres/K8s |
| 安全扫描记录 | check_secrets.py → eval/security-scan.json：0 findings；外部评审未排期 |
| 验收包 | tools/pilot_pack.py → eval/pilot-pack.md：G5 false，阻塞 6 项 |
| 值班/验收文档 | docs/pilot-acceptance.md、docs/oncall.md |
| 测试 | 新增 test_m5_closure 2；引擎 356 |

### 10.37 里程碑收口审计与 P0 修复（2026-10-29）

| 项 | 实现 |
|---|---|
| 审计文档 | docs/milestone-audit.md：M0–M5 门禁、代码债 C1–C10、数据 D1–D4、外部 E1–E6 |
| 指标修复 | observability 按指标族只输出一次 HELP/TYPE；engine_jobs/queue 分组输出 |
| 直方图 | runner 每任务写 metrics.json（pipeline_seconds）；/metrics 输出 engine_pipeline_seconds 直方图（60/120/300/600/+Inf），告警指标可用 |
| 证据定位 | FieldRisk 增加 evidence_id/page_no；API RiskFieldOut 透出；字段复核表加“定位”跳预览 |
| 验证 | 引擎 356、平台 19、web typecheck/vitest 通过 |
| 后续 | C4 lane 隔离、C5 定向覆盖修复、C6 classification recipe、C10 OpenAPI |

### 10.38 C5 覆盖语义与 C6 表型/配方修复（2026-10-29）

| 项 | 实现 |
|---|---|
| C5 覆盖语义 | coverage/plan.py：无对应表型且无 unknown 表 → required 记 not_applicable；有 unknown 仍 missing；新增 test_coverage_applicability 3 个 |
| C6 表型 | tablegrid/profile.py 扩充 mechanical/inspection/dimension/classification 标记；257 表 unknown 41→0 |
| C6 配方 | 新增 classification_v1（active，nonrecord 合同），active 配方 7 个；绑定率维持 0.9718 |
| C6 指标 | routing production 61/explore 173/human 23；文档级 production 0.95；novelty 0.3385→0.0000；T3 0.3385→0.0000；coldstart T1 61/T2 196/T3 0 |
| M3 评测 | C5 后 3 文档 STP 0.3333、8 文档 0.25 不变；根因是 mock 抽取无 grade、31/32 页超预算、top2 歧义，非覆盖判定 |
| 测试 | 引擎 359 通过；平台 19；web typecheck |
| 结论 | G2.5 条件达成（20/25 样本）；G3 仍未通过（STP <0.80） |

### 10.39 C5b 页预算与歧义规则（2026-10-29）

| 项 | 实现 |
|---|---|
| 页预算 | orchestration Budget.max_pages 30→60；30 页仅作 SLA 压测口径，31/32 页文档恢复处理 |
| 歧义规则 | routing：top2 同族分差 ≤0.05 时用表头 family 计数（拉伸/屈服/冲击 vs 硬度/HBW）消歧；机械证据 ≥2 且领先 ≥1 选 mechanical，否则仍 human |
| 路由 | 表级 human 31→19、production 61→66；文档级 production 0.95；novelty/T3 保持 0 |
| STP | 8 文档 0.25→0.375（3 published/1 review/4 human）；3 文档 0.333；p95 708ms |
| 剩余阻塞 | mock 抽取无 grade（2 份）、化学值越界（1 份）、真歧义（1 份）、review（1 份） |
| 测试 | 新增 2 个（Budget 60、header 消歧）；引擎 361 通过 |
| 产物 | 刷新 eval/recipes/routing.json、eval/m3*.json、eval/coldstart.*、eval/loadtest.* |

### 10.40 真实 Qwen 8 文档复跑与三项根因修复（2026-10-29）

| 项 | 实现 |
|---|---|
| 环境 | 模型机 IP 由 `192.168.188.75` 改为 `192.168.1.35`；SSH 可达但 9989 未监听，按 `metal-doc-agent-runtime/start_qwen35_9b.sh --detach` 启动 Qwen3.5-9B（16K / 0.35 / 2 seq），约 1 分钟后 ready |
| 根因 1 表型 | OCR 分页把下一张表的标题挂到力学续表（T6 caption 为“表5 化学成分”），`profile.py` 按标题判 chemical，`N/mm²` 中的 N 被当作元素列，520 MPa 触发 `CHEMICAL_OUT_OF_RANGE`；改为表头强信号优先（元素列 ≥3 / 检验 / 力学 / 分类），标题只在表头 unknown 时兜底；dimension 与“牌号”仅作弱信号 |
| 根因 2 跨行 | 源 HTML rowspan 多算（如 `rowspan=6` 覆盖 5 个数据行），下一牌号行继承陈旧跨行后整行右移，Z 列读到 Rm=1000；`_expand_grid` 改为惰性跨行，并在“溢出量 ≥ 已填充跨行”时丢弃陈旧跨行；`_repair_collapsed_columns` 增加表头越界触发；GB/T 33084 续表恢复 10 列对齐 |
| 根因 3 映射/单位 | Qwen 模型把硬度列重复绑定为 A/Z，按行序覆盖规则列（A=250、Z=260）；`_map_columns` 增加属性唯一约束（规则已占用则忽略模型重复绑定）。`parse_unit` 将 `N/mm²` 归一为 MPa，消除 86 条 `UNIT_MISMATCH` |
| STP | 真实 Qwen 8 文档 **0.75**（6 published / 2 human）；p95 170.6s、中位 71.0s、总耗时 638s；同代码 mock 0.375→0.625 |
| 剩余阻塞 | `gbt14992_2015` route_human（签名分 0.65–0.72、risky_table_size）；`gbt3191_2010` coverage_gap（非记录表无 grade 记录，另有 chemical ambiguous） |
| 测试 | 新增 5 个（表型优先级 2、跨行泄漏 1、属性唯一绑定 1、N/mm² 1）；引擎 364、平台 19、web 5 全绿 |
| 产物 | `eval/m3-qwen-8docs.json` / `.md`、`eval/m3-8docs-after3.json`；compose/.env/monitoring/NetworkPolicy/security 的模型平面地址同步为 `192.168.1.35` |

### 10.41 表型顺序修正与 G3 达成（2026-10-29）

| 项 | 实现 |
|---|---|
| 根因 | `profile.py` 的表型顺序把力学表（含“试样状态”列）判成 inspection；检验项目表把“化学成分”列为检验项却判成 chemical；电导率表含“力学性能”引用列被判成 mechanical，导致 required coverage `mechanical_properties` ambiguous |
| 规则 | 元素列 ≥3，或“化学成分”且非检验项目表（检验项目/取样规定/章条号/试验方法）→ chemical；具体力学属性列（Rm/Rp0.2/A/Z/KV2/HB/HRC/HV/抗拉/屈服/伸长/收缩/冲击/硬度）→ mechanical；检验标记 → inspection；单“力学性能”仅在无检验标记时生效 |
| 影响 | `gbt3191_2010` coverage_gap→published（机械记录 56→78）；`gbt3880_1_2012` 电导率表回归 inspection，避免 mechanical ambiguous |
| STP | 真实 Qwen 8 文档 **0.75→0.875**（7 published / 1 human）；同代码 mock 0.375→**0.875**；p95 169.5s、中位 103.6s、总耗时 759s |
| 剩余人工 | `gbt14992_2015`：13 张化学表同配方、签名分 0.65–0.72，2 张多 block 触发 `risky_table_size`，保留人工 |
| 路由/冷启动 | production 70→73、explore 168→164、human 19→20；T1 70→73/T2 187→184；unknown 保持 0、绑定率 0.9718 |
| 测试 | 新增 3 个（试样状态力学表、检验项目含化学成分、电导率引用力学性能）；引擎 367、平台 19 通过 |
| 产物 | `eval/m3-qwen-8docs.json` / `.md`、`eval/m3-8docs-after5.json`；`eval/recipes/routing.json`、`eval/coldstart.*`、`eval/recipes/binding-coverage.json` 刷新 |
| 阶段门 | **G3 达成**（STP 0.875 ≥ 0.80；修复 3/3、无死循环、成本可核算、压缩无损、批量幂等、checkpoint 可恢复） |

### 10.42 C4 任务 lane 与 worker 池隔离（2026-10-29）

| 项 | 实现 |
|---|---|
| 契约 | `JobState.lane`：`production` / `explore` / `human`，默认 `production`；旧 `state.json` 缺字段时按 production 回填 |
| 存储 | `JobStore.reserve(lane=...)` 落盘；`list(lane=...)` 按 lane 过滤 FIFO；非法 lane 抛 `ValueError` |
| API | `POST /v1/jobs` 与批量 item 支持 `lane`（表单/字段）；`GET /v1/jobs?lane=` 过滤；未知 lane 返回 422；幂等键包含 lane，避免跨池回放 |
| worker | 新增 `--pool`（或 `WORKER_POOL` env），只消费该 lane 的 queued 任务；未设置时保持全量消费（兼容旧部署） |
| 部署 | compose 与 K8s 的 `WORKER_POOL` 由 `prod` 改为 `production`，与契约枚举一致，避免 worker 启动被 `parser.error` 拒绝 |
| 边界 | 任务 lane 在提交时确定（路由前置）；orchestration 内部 route.queue 只影响发布/人工终点，不回写 lane |
| 测试 | 新增 4 个（lane 默认与 list 过滤/非法 lane、worker pool 只跑本 lane、API lane 过滤与 422）；引擎 370、平台 19 通过 |

### 10.43 C10 OpenAPI 字段复核端点（2026-10-29）

| 项 | 实现 |
|---|---|
| 草案 | `docs/openapi/standard-extraction.yaml` 新增 `GET/POST /v1/documents/{id}/field-reviews`、`POST .../field-reviews/batch`、`GET .../field-diff`、`GET .../review-risks`，均 `x-status: implemented` 且带 `operationId` |
| Schema | 新增 `FieldReviewRequest`、`FieldReviewBatchRequest`、`FieldReview`、`FieldDiff`、`RiskField`、`DocumentRisk`，与 `hanson_api/schemas.py` 对齐 |
| 导出 | 重新生成 `packages/contracts/openapi.json`（62 paths），与线上组合 app 一致 |
| 测试 | `test_openapi` 增加草案与导出契约的 4 条端点断言；3 个 OpenAPI 测试通过 |

### 10.44 C8 模型 token 逐任务记账（2026-10-29）

| 项 | 实现 |
|---|---|
| 客户端 | `OpenAICompatibleClient` 解析响应 `usage`，累计 `prompt/completion/total_tokens` 与调用次数；Qwen/GLM 共用 |
| 抽取器 | `QwenExtractor.usage` 汇总 native 与 SFT 客户端；pipeline `trace.json` 写 `model_usage` |
| 编排 | `PipelineTools` 跨重试累计 token，`state.cost.model_tokens` 落 `m3_trace`；`JobState.summary.model_tokens` 与 `metrics.json` 同步 |
| 成本 | `tools/cost_report.py` 读 trace token；`infra/cost_model.json` 新增 `token_per_1k`（单价仍待业务确认） |
| 测试 | 新增客户端 usage 累计测试；引擎 371 通过 |
| 限制 | 旧 run 无 `model_usage` → 0 token；金额仍为 0，直到填入单价（E4） |

### 10.45 C7 反馈抽检与修正正确率（2026-10-29）

| 项 | 实现 |
|---|---|
| 抽样 | `tools/feedback_sample.py`：按 `seed+event_id` 哈希排序抽样，同参数重跑样本稳定；`--rate/--limit` 控制规模 |
| 标注接口 | `data/feedback/annotations.jsonl`：`{event_id, verdict: correct/incorrect/unsure, reason}`；工具读取后计算 accuracy 与 by_action/by_risk |
| 富化 | 从 replay runs 关联 `field_risks`，样本带 `risk_level/evidence_id/page_no` |
| 产物 | `eval/feedback.json` / `.md`、`eval/feedback-samples.jsonl`（当前 0 事件，accuracy=null） |
| 测试 | 新增 2 个（确定性抽样、正确率计算）；引擎 373 通过 |
| 限制 | 真实反馈事件与领域标注仍缺（D3），accuracy 待试点后回填 |

### 10.46 C9 备份加密与 E1–E5 外部阻塞准备（2026-10-29）

| 项 | 实现 |
|---|---|
| C9 加密 | `backup.sh` 用 `openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt` 加密 `.dump/.tgz`，口令 `BACKUP_PASSPHRASE`/文件；对象存储打包为 `objects.tgz`；`SHA256SUMS` 覆盖密文 |
| C9 恢复 | `restore.sh` 先校验密文、再解密到临时目录、恢复后清理；支持 `objects.tgz` |
| C9 演练 | `drill.py` 增加 Fernet 加密/解密与篡改检测：`checks.tamper_detected=true`，本地演练 PASS；`postgres_drill.sh` 供试点环境对比 `documents/field_review_events/audit_logs` 行数 |
| E1 | `tools/sla_probe.py`：从 JobStore 计算可用性/失败率/p95/错误预算；当前 14 jobs → `insufficient_data`，工具与字段就绪 |
| E3 | `docs/security-review-package.md`：范围、控制清单、已知风险、证据索引、评审方检查清单、签字栏；密钥扫描 0 findings |
| E4 | `infra/cost_model.json` 增加 `pending_fields/confirmed_by/confirmed_at`；`token_per_1k` 就绪，金额待单价 |
| E5 | `docs/pilot-acceptance.md` 增加 E1–E5 输入表；`docs/oncall.md` 增加 4 周排班表与临时升级规则 |
| 验收包 | `tools/pilot_pack.py` 读取 `sla.json`，SLA 由 `gap` 改为 `partial`；G5 仍为 false，阻塞 6 项 |
| G5 指标回归 | 表型补充“碳当量/CEV/Pcm → 化学”“工艺参数 → 检验”，修复 dimension 绑定率 0.9444 拖累；五族恢复 operational（dimension 1.0，整体 0.9718，unknown 0）；routing production 76 / explore 161 / human 20，T1 76 |
| 测试 | 新增 `test_sla_probe` 1 个、表型 2 个、备份演练断言 2 个；引擎 376、平台 19 通过 |
| 仍待外部 | 试点流量、Postgres/K8s 环境、外部评审排期、业务单价、试点/值班名单 |

### 10.47 M2.5/G4 收口：52 份语料、admin 表型、抽取级影子与 E2E 复核走查（2026-10-30）

| 项 | 实现 |
|---|---|
| 语料 | `runs/corpus_ext` 新增 32 份（`markdown/` 去重 sha+标题，页数 5–60、关键词 ≥4），`runs/corpus50` 以 junction 合并 20+32=52 份；有效文档 50 份 |
| admin 表型 | `tablegrid/profile.py` 增加 `ADMIN_MARKERS`、标准号识别与空表头判定：封面/会签/审签/修改履历/文件与产品清单/引用标准表 → `admin`，不进入路由与 novelty/T3 分母 |
| 表型补充 | inspection：检验类型/频次、抽样水平/数量、试验和检查/标准/项目、热处理条件、锻比/操作说明/锻造方式/锭型、夹杂物分类、英文 inspection 标记；mechanical：疲劳/应力比/最大应力/室温/高温；chemical：组分/元素含量；dimension：长/短试样、交付规格/公差要求 |
| 抽取级影子 | `recipes/shadow.py::evaluate_field_shadow`：按候选 `signature.profile/orientation` 重放 MockExtractor，逐 `(record_id, property)` 比较 comparator/上下界/单位/文本；核心字段（Rm/Rp0.2/A/Z/KV2/硬度、化学元素）回归即失败；`tools/shadow_run.py` 输出 `field_shadow` 与 `overall_passed` |
| 单位 | `normalize.parse_unit` 支持 `RmMPa`/`A%`/`KU1J` 紧贴写法（`%`/`MPa`/`J` 直判）；`extraction/mock.py` 增加 `DEFAULT_UNITS`（KV2/KU2→J、Rm/Rp0.2→MPa、A/Z→% 等） |
| 风险校准 | `review/risk.py`：`HIGH_RISK_PROPERTIES` 补 HB；新增 `REVIEW_MEDIUM_PROPERTIES`，仅关键力学属性/CEV/Pcm 的开放区间记 medium，化学元素常规上限记 low |
| G3 压缩 | `orchestration/context.py::context_regression` 增加 `fields_before/after/lost_fields/field_loss_rate`，抽取字段集合纳入 lossless 判定 |
| 路由/指标 | `tools/route_eval.py`、`recipes/coldstart.py` 跳过 admin 表；冷启动分母改有效文档（50） |
| E2E | `e2e/test_main_flow.py` 增加字段复核 tab → 「定位」深链 viewer → 返回 → 接受 → 退出；`run_main_flow.ps1` 用 `Start-Process -RedirectStandard*` 落盘测试 stdout/stderr |
| 结果 | 52 份 silent **0**；coldstart hit 0.9000、novelty/T3 0.0267（450 表，T3 12）；routing production 150/explore 255/human 45；影子 111 表 field 1.0/core 0；风险 high 0/medium 1704/low 4729；文档 medium 26/low 26 |
| 测试 | 新增抽取级影子 3 个、风险分级 1 个、压缩字段断言；引擎 **380**、平台 19、Web typecheck + 5、E2E 1 通过 |
| 产物 | `eval/coldstart-52.json/.md`、`eval/recipes/routing-52.json`、`eval/recipes/shadow-candidate_mechanical_properties_66a957cb.json`、`eval/m4-52.json/.md` |

### 10.48 长时评测：语料扩至 164 份、真实 Qwen 准确率/耗时与 SFT 候选集（2026-10-30）

| 项 | 实现 |
|---|---|
| 语料选取 | `tools/select_corpus.py`：catalog 408 → 去重/页数 4–80/类型配额，新增 112 份（技术条件 19、制造大纲 20、质保 6、内部 5、未分类 60、企业 1、待定 1）；`tools/replay_corpus.py` 逐份重放并写 `timings.jsonl` |
| 分页 | `ingest.PAGE_RE` 支持 `<!-- page: N -->`（`markdown/` 语料），修复 144 份 `page_count=1` 与证据页码；新增 `PageSplitTests` |
| 表型 | 补充测量表/日文厚度/质保要求/审批变更/夹杂物/尺寸公差等标记；164 份 T3 15.67%（标准类 0%） |
| 表头修复 | `tablegrid/parser.py::_header_grade_shifted`：牌号 rowspan 覆盖全部表头行且被子表头填充清空时触发重排；gbt4437 T2 列错位修复，Field F1 0.2203→0.8398、Value 0.1884→1.0；新增回归测试 |
| 真实 Qwen | 20 份金标：Record F1 0.8771、Field 0.8156、Value 0.9134、Evidence 1.0、Coverage 0.9625、silent 0；p50 65.7s/p95 172.0s/4.29s 每页/45.1 份每小时；17/20 触发模型、65,787 token |
| 新类型抽样 | 10 份（191 页/131 表）：p50 43.0s/p95 117.5s/2.55s 每页；证据 1.0、silent 0 |
| 样本 | `tools/build_pseudo_sft.py`：证据逐字段校验的伪样本（Qwen 27 + mock 32，去重后 58）；`data/m2/sft-v3-candidate` 训练 750 / 评测 110（评测集不变） |
| 训练 | 未执行：9B LoRA 需模型主机 `/home/grainuser/models/models/Qwen3.5-9B` 与 GB10；本地 4070 8GB 且无主机 shell；命令与数据已备 |
| 文档 | `docs/extraction-accuracy-latency-2026-10-30.md`；证据 `eval/extraction-report.*`、`eval/qwen-gold-v2/eval.*`、`eval/m4-164.*`、`eval/coldstart-164.*` |
| 测试 | 引擎 **382** 通过（新增分页/rowspan 2 个） |

### 10.49 adapter-v3 训练、231 份语料与真实模型评测（2026-10-30）

| 项 | 实现 |
|---|---|
| 模型主机 | `192.168.188.75`（GB10）；SSH `grainuser`；adapter 服务 9990 启动，base vLLM 9989 在该机未安装 |
| 语料 | 新增 67 份（总 231）；有效表 1326、admin 790；T3 20.14%（标准类 0%）；silent 0/231；绑定率 0.935 |
| 样本 | `tools/build_pseudo_sft.py` 支持 header/row 双任务、doc_id=run 目录、同签名最多 3 条；伪样本 370（row 190/header 180），覆盖 72 份/167 表；`data/m2/sft-v4-candidate` 995/110 |
| 训练 | 模型服务器 `run_m2_lora.sh`，992 训练/110 评测，2 epoch/124 步/2884.9s，train_loss 0.0398，eval_loss 0.0669；产出 `adapter-v3` |
| 推理 | `serve_adapter.py` 9990（transformers，无 vLLM）；`/health` 正常；qdu302 冒烟 1.0 |
| 客户端修复 | `_ask_row_sft` 改用 `sft_client or client`；新增 `METAL_DOC_SFT_RULES_FIRST`（规则完整时不调模型） |
| 评测 | base native Field 0.8156/Value 0.9134/p95 172s；adapter 全映射 0.8106/0.9069/p95 325s；rules-first 0.7999/0.9132/p95 53s |
| 人工复核 | `tools/export_manual_review.py` 输出 machine/gold/证据/匹配标记；adapter 全映射 1199 字段、匹配 885、不匹配 120、漏抽 194 |
| 文档 | `docs/adapter-v3-training-evaluation-and-pipeline-2026-10-30.md`（含端到端解析流程） |
| 证据 | `eval/adapter-v3-gold/*`、`eval/adapter-v3-gold-rulesfirst/*`、`eval/extraction-report-adapter-v3*`、`eval/manual-review/*`、`eval/pseudo-coverage.json`、`eval/corpus-231-structure.json` |
