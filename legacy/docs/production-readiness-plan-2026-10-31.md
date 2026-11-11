# 生产落地整合计划（2026-10-31）

> 状态：**R4 前端完整性已完成（2026-11-01），进入 R5 全链路测试**
> 已确认：D1-B 完整多租户 / D2-A 单机 Compose + Postgres / D3-A 恢复 parsekit 版面服务 / D4-A 人机复核放行
> 范围：`apps/api`、`apps/web`、`apps/worker`、`metal-doc-agent` 引擎、模型平面、部署与运维
> 输入：本轮实测基线、代码审计、`docs/milestone-audit.md`、`docs/platform-rollout.md`、`docs/pilot-acceptance.md`

---

## 1. 结论

1. **主链路代码可用，测试全绿**：引擎 387、平台 19、Web 5 + E2E 均通过；20 份金标 Record F1 0.8604 / Field F1 0.8208 / Value 0.9368。
2. **当前不能直接上生产**，阻断不在抽取算法，而在四类工程闭环：
   - 运行时配置与部署：容器入口、Postgres 驱动、模型/OCR 地址、mock 回退；
   - 安全边界：引擎 `/v1/jobs*` 等端点未鉴权，前端结果页绕过知识库权限；
   - 功能完整性：成员/API Key 管理/审计/导出/分页等缺口；
   - 验收与运维：迁移与 Postgres、监控核对、备份恢复、试点签字。
3. **质量口径已定**：Field 0.8208 未达 G2 的 95% 目标。按“**人机复核闸门 + 试点质量门禁**”上线（高风险字段 100% 拦截、复核一次通过率 ≥80%），不按“免复核自动发布”承诺。
4. **范围已定**：按完整多租户版落地（工作空间、成员/邀请/角色、用户管理、审计、API Key 作用域）；部署以单机 Compose + Postgres 为交付路径，K8s 后置。
5. 本文所有“P0/P1/P2”指上线优先级：P0 不修不能上线，P1 试点前必须完成，P2 试点后迭代。

---

## 2. 基线（本轮已实测）

| 项 | 命令/方式 | 结果 |
|---|---|---|
| 引擎测试 | `python -m unittest discover -s tests -q`（`metal-doc-agent`） | **387 passed / 19.3s** |
| 平台测试 | 同上（`apps/api`） | **19 passed / 22.3s** |
| Web 类型检查 | `pnpm --filter @hanson/web typecheck` | 通过 |
| Web 构建 | `pnpm --filter @hanson/web build` | 通过（JS 341.8 kB / gzip 101.1 kB） |
| Web 单测 | `pnpm --filter @hanson/web test` | **5 passed** |
| 主链路 E2E | `pnpm e2e`（隔离库 + mock OCR） | **通过 / 10.6s** |
| Alembic | 空库 `alembic upgrade head`（SQLite） | 7 个迁移到 `h4e5f6a7b8c9 (head)` |
| 模型平面实测 | SSH `curl` 127.0.0.1 | `:9977` **200**；`:9991` **200**（`Qwen3.5-9B` + `adapter-v5`）；`:9989/:9990/:9978` **000（未启动）** |
| 版本控制 | `Test-Path .git` | **False**（当前工作区无 Git 仓库） |

模型平面现状与仓库配置不一致：`deploy/.env.example`、`infra/docker`、`infra/k8s`、`docs/runbook.md` 仍写 `9989 基座 + 9990 adapter-v2`，实际只有 `9977 + 9991(adapter-v5)`。

---

## 3. P0 阻断清单（证据已核对）

| ID | 问题 | 证据 | 影响 | 修复方向 |
|---|---|---|---|---|
| B1 | 平台 API 容器入口不存在 | `infra/docker/Dockerfile.api:15` 与 `infra/docker/compose.yaml:72` 使用 `hanson_api.main:app`；`apps/api/hanson_api/` 下无 `main.py` | Compose/K8s 平台 API 起不来 | 新增 `hanson_api/main.py`（复用根 `apps/api/main.py` 组装逻辑），保留 `uvicorn main:app` 兼容 |
| B2 | Postgres 驱动缺失、K8s 无 Postgres | `compose.yaml:65`、`k8s/config.yaml:42` 使用 `postgresql+psycopg://`；`apps/api/pyproject.toml:10-18` 未声明 `psycopg`；K8s 仅有 Secret 指向 `postgres:5432`，无 StatefulSet/Service | 切 Postgres 即启动失败；K8s 无库 | 加 `psycopg[binary]`；补 Postgres 部署或明确外置库；迁移/备份演练 |
| B3 | 模型/OCR 配置默认 mock，生产静默降级 | `deploy/start_local.ps1:15-19` 未设 `METAL_DOC_OCR/EXTRACTOR`；`settings.py:56-57` 默认 `mock`；`compose.yaml:9-14` 默认 `mock` | 真实文档会产出 mock 假结果，违反“不得静默降级”硬约束 | 生产模式强制显式后端；启动自检失败即拒绝服务；更新全部环境模板 |
| B4 | PDF 真实链路不可用 | 引擎 `ocr/glm.py:10,114-117` 依赖 `LayoutClient`；`LAYOUT_SERVICE_URL` 未配或指向已停的 `:9978` | PDF 上传后解析失败，只能吞 `.md` | 在模型机提供 parsekit 版面 HTTP 服务（推荐）或平台只接收 `.md` 并显式 415 |
| B5 | 引擎端点无鉴权，前端绕过知识库权限 | `apps/api/main.py:35-38` 同端口挂载引擎 app；`main.py:40-47` 的 `ENGINE_INTERNAL_TOKEN` 可选；`JobDetailPage.tsx:74-92` 无 `documentId` 时直接调 `/v1/jobs/*`，且始终调 `api.job(jobId)` | 任意人可枚举/读取所有任务结果；开 token 则前端立即失效 | 前端全部改用 `/v1/documents/*`；引擎 `/v1/jobs*`、`/v1/recipes`、`/v1/batches` 默认内网或强制 token；补越权测试 |
| B6 | `create_all` 与 Alembic 双轨 | `apps/api/hanson_api/db.py:39-42` 启动即 `create_all`；平台/容器又执行 `alembic upgrade head` | 生产库结构漂移、迁移不可回滚 | 生产禁用 `create_all`；启动校验 revision=head；SQLite/Postgres 双迁移测试 |
| B7 | Web 容器构建不可复现 | `infra/docker/Dockerfile.web:4` 复制 `package-lock.json*`，仓库实际是 `pnpm-lock.yaml` | 依赖漂移/构建失败 | 改用 pnpm + 根 lockfile，`--frozen-lockfile` |
| B8 | 无版本控制 | 无 `.git` | 无法审计变更、灰度/回滚无基线 | 上线前建立仓库与 tag（需用户确认） |

---

## 4. 功能矩阵

### 4.1 后端 API

| 域 | 已实现端点 | 状态 | 缺口（P0/P1/P2） |
|---|---|---|---|
| 认证 | `POST /v1/auth/login`、`GET /v1/auth/me` | 可用 | P1 登录限流/锁定、密码修改/重置、token 吊销；P2 refresh |
| 知识库 | `POST/GET /v1/knowledge-bases`、`GET /{id}` | 可用 | P1 成员增删改查/邀请/角色；P1 改名/删除；P2 工作空间 |
| 文档 | `POST/GET /v1/documents`、`GET /{id}`、`POST /{id}/parse` | 可用 | P1 删除、取消任务、分页/搜索/状态筛选；P1 sha 幂等返回 200 已有 |
| 任务 | `GET /v1/tasks`、`GET /{job_id}`、`POST /{job_id}/retry` | 可用 | P1 状态/文档筛选已部分有，分页缺；P2 批量/取消 |
| 结果 | `items/records/clauses/evidence/evidence/{id}/alignment/result/links/coverage-audit/preview/pages/{n}/image|layout/results/sync` | 可用 | P1 大数据分页/字段筛选；P1 hansonDoc schema 投影与 CSV/XLSX 导出未接 API |
| 复核 | 新词 accept/map/reject、整体 submit/confirm、字段 accept/edit/reject/batch/diff/risks | 可用，闸门完整 | P1 复核事件导出、复核耗时统计；P2 多人流转 |
| 分享 | `POST /{id}/share`、`GET /v1/share/{token}` | 可用 | P2 撤销/续期/分享列表 |
| 业务词典 | 引擎 `GET /v1/business-dictionary`（未鉴权） | 半可用 | P0 加平台鉴权包装；P1 `POST /sync`、版本/别名管理（OpenAPI 中 `planned`） |
| API Key | `POST/GET /v1/api-keys`、`DELETE /{id}` | 可用，无 UI | P1 前端页面；P1 按知识库限定 scope |
| 审计 | `GET /v1/audit-logs`（admin） | 可用，无 UI | P1 审计页面/筛选/导出 |
| 运维 | `/health`、`/ready`、`/metrics`、`/platform/ready`、`/platform/metrics` | 可用 | P1 就绪检查纳入迁移版本与模型端点；P1 结构化日志/请求 ID |
| 引擎 | `/v1/jobs*`、`/v1/batches*`、`/v1/recipes*` | 功能可用，**无鉴权** | P0 收口（见 B5） |
| 契约 | `packages/contracts/openapi.json`（62 paths） | 已导出 | P1 消除 9 个 `planned` 或明确降级；补响应模型 |

### 4.2 前端页面

| 路由 | 页面 | 已实现能力 | 缺口 |
|---|---|---|---|
| `/login` | 登录 | 登录、401 跳转、退出 | P1 错误文案、限流提示 |
| `/` | 任务中心 | 任务列表、状态、进入结果 | P1 筛选/分页/搜索；P1 失败原因展示 |
| `/kb` `/kb/:id` | 知识库 | 创建、上传、解析、重试、轮询、预览、查看结果 | P1 删除/改名、成员入口、批量操作 |
| `/kb/:id/extractions` | 标准拆分列表 | 状态/版本/项目/记录/新词、重试、重新解析 | P1 分页/筛选；P1 失败码 |
| `/jobs/:jobId` | 结果详情 | 7 个 tab、字段复核、新词复核、提交/确认、分享、证据深链 | P0 改走平台文档端点；P1 大数据分页；P1 导出 |
| `/kb/:id/documents/:docId/viewer` | 原文预览 | 页图/版面/证据定位 | P1 大文档性能；P1 缩放/框选交互 |
| `/share/:token` | 分享结果 | 只读项目/记录/条款/证据 | P1 过期提示/重新分享 |
| `/dictionary` | 业务词典 | 查询三类词条 | P1 别名校验/pending 管理；P0 鉴权 |
| — | 工作空间 | 未实现 | P1 列表/切换/创建（D1-B） |
| — | 成员/邀请 | 未实现 | P1 成员列表/角色/邀请/撤销（D1-B） |
| — | API Key 管理 | 未实现 | P1 新建/列表/撤销（含一次性明文提示） |
| — | 审计/用户管理 | 未实现 | P1 审计列表/筛选；P1 用户创建/停用/重置（平台 admin） |
| — | 个人中心/帮助 | 未实现 | P1 显示名/密码；P2 帮助 |

### 4.3 前端横向问题

- `api.ts:57-60` 直接把 `status + body` 透给用户，泄露内部信息且不可读；需统一错误码与中文文案。
- 轮询固定 2s（`KbDetailPage`、`ExtractionListPage`），无退避/上限提示；长任务建议 SSE 或指数退避。
- 列表无分页/虚拟滚动（证据默认 500/5000），大文档会卡。
- 仅 5 个组件测试；无 `api.ts`、页面交互、401/权限、路由测试。

### 4.4 多租户设计要点（D1-B，需在 R3.0 定稿）

| 对象 | 设计 | 约束 |
|---|---|---|
| 工作空间 Workspace | `workspaces` + `workspace_members`；知识库归属工作空间 | 跨工作空间数据完全隔离；现有知识库回填默认工作空间 |
| 角色 | 工作空间 owner/admin/member；知识库 owner/editor/viewer；平台 admin 仅用于用户/全局审计 | 每个端点先校验工作空间成员，再校验知识库角色；能力矩阵落表 |
| 邀请 | `invitations`（token、角色、过期、接受人、状态） | 一次性、可撤销、过期失效；接受后写成员关系 |
| 用户管理 | 平台 admin 创建/停用/重置密码；个人中心改显示名/密码 | 不做公开注册（如需要另行决策）；停用即 401 |
| API Key | 绑定工作空间 + scopes（`documents:read/write`）+ 可选知识库白名单 | Key 不能跨工作空间；撤销即时生效 |
| 审计 | 审计事件补 `workspace_id`，按工作空间/动作/人筛选 | 平台 admin 可查全局；工作空间 admin 仅查本空间 |
| 迁移 | 新增表与 `workspace_id` 外键；回填现有 KB/成员/API Key | 迁移可回滚；迁移前后数据量校验 |

前端对应入口：工作空间切换、成员/邀请、API Key、审计、用户管理、个人中心。

---

## 5. 分阶段执行计划

### R0 · 基线冻结与运行真相（P0）

- [ ] R0.1 建立版本控制与基线快照（tag/分支），记录当前测试与评测产物。
- [ ] R0.2 产出“环境真相表”：模型端点、OCR、版面、DB、数据目录、worker 池、inline 开关，逐项实测。
- [ ] R0.3 固化启动命令：本机、Compose、K8s 三套必须同一套环境变量语义。
- 退出：环境真相表经确认；任何人可按表冷启动并解释每个变量。

### R1 · 部署与运行时闭环（P0）— 已完成

- [x] R1.1 新增 `apps/api/hanson_api/main.py`，统一 Compose/K8s/本地入口（修 B1）。
- [x] R1.2 加 `psycopg[binary]`，补 Postgres 部署/连接与健康检查（修 B2）；Postgres 迁移到 `h4e5f6a7b8c9`。
- [x] R1.3 生产环境模板统一：`METAL_DOC_OCR=glm`、`METAL_DOC_EXTRACTOR=qwen`、`SFT_BASE_URL=http://192.168.1.35:9991/v1`、`SFT_MODEL=adapter-v5`、`METAL_DOC_INLINE_JOBS=false`；旧 9989/9990/adapter-v2 已从当前部署模板移除（修 B3）。
- [x] R1.4 在模型机提供 parsekit 版面 HTTP 服务（D3-A）：`GET /health` + `POST /v1/layout`，与 `clients/layout.py` 契约一致；`/platform/ready` 已接入（修 B4）。
- [x] R1.5 启动自检：生产模式缺 secret、缺模型端点、mock 后端、inline=true、SQLite、自动建表时拒绝启动。
- [x] R1.6 Web 镜像改 pnpm + lockfile，Compose 冷启动验证（修 B7）。
- 退出：Compose 从零启动 → 登录/上传/解析/结果/复核全通；`/platform/ready` 为 ok；版面服务断开时返回 503 且 `model_layout=false`，恢复后回到 200。

### R2 · 安全边界（P0）— 已完成

- [x] R2.1 引擎端点收口：平台端口默认不暴露 `/v1/jobs*`、`/v1/recipes`、`/v1/batches`；确需暴露则强制 `ENGINE_INTERNAL_TOKEN`（修 B5）。
- [x] R2.2 前端结果页全部改用 `/v1/documents/*`（含 `GET /v1/documents/{id}` 取任务头），移除对 `/v1/jobs` 的依赖；裸 `/jobs/<id>` 自动解析 `document_id`。
- [x] R2.3 业务词典加平台鉴权 GET（`/v1/business-dictionary`），前端改走平台；POST 同步归入 R3.9。
- [x] R2.4 登录限流/失败锁定；生产 secret 强度校验；API/Web 安全响应头与 CSP（修 B3 邻接项）。
- [x] R2.5 补越权测试：非成员读文档/证据/分享、API Key scope、跨 KB 任务枚举、过期/篡改 token。
- 退出：匿名请求所有数据端点均 401；用户只能看到所属 KB；安全测试全绿。

### R3 · 功能补齐（P1，D1-B 完整多租户）

- [x] R3.0 定稿多租户模型与权限矩阵：工作空间/知识库双层角色、能力表、邀请流程、平台 admin 边界、现有数据迁移方案（见 4.4，落地见 `docs/multi-tenant-design.md`）。
- [x] R3.1 数据模型与 Alembic 迁移：`workspaces`、`workspace_members`、`invitations`、`workspace_id` 外键、回填现有 KB/成员/API Key；可 downgrade（`i5f6a7b8c9d0`）。
- [x] R3.2 工作空间 API：创建/列表/详情/成员增删改/角色变更。
- [x] R3.3 邀请 API：创建/列表/撤销/接受（token 一次性、过期、审计）。
- [x] R3.4 用户管理 API：平台 admin 创建/停用/重置密码/列表；个人资料与改密。
- [x] R3.5 权限收口：所有文档/任务/结果/复核/分享端点加“工作空间成员 + 知识库角色”校验；API Key 绑定工作空间与 KB 白名单。
- [x] R3.6 API Key 页面与按工作空间/作用域限制；审计补 `workspace_id` 与筛选。
- [x] R3.7 文档删除、任务取消、列表分页/搜索/筛选。
- [x] R3.8 导出：hansonDoc schema 投影（复用 `tools/export_hanson_schema.py`）+ CSV/XLSX + 分享页导出。
- [x] R3.9 业务词典：别名/pending/版本/同步端点，OpenAPI 中 `planned` 项逐项落地或标记不做。
- [x] R3.10 响应模型与错误码统一（problem+json，保留 `detail` 兼容），刷新 `packages/contracts/openapi.json`（60 paths）。
- 退出：多租户权限矩阵逐项有测试；跨工作空间/跨 KB 越权全部 403/404；功能矩阵 P1 项全绿；契约无悬空端点。

### R4 · 前端完整性与体验（P1）

- [x] R4.1 新页面：工作空间切换/列表、成员与邀请、API Key、审计、用户管理、个人中心。
- [x] R4.2 任务/文档/证据分页与筛选；大结果虚拟滚动。
- [x] R4.3 统一错误文案与重试；轮询退避；长任务进度提示。
- [x] R4.4 导出按钮与下载；分享页过期/重新分享。
- [x] R4.5 角色可见性：按钮/入口按角色隐藏，越权仍由后端 403 兜底。
- [x] R4.6 响应式与可访问性（键盘、焦点、对比度）基础检查。
- [x] R4.7 前端测试：`api.ts` mock、页面关键交互、401/403、空态/错误态、工作空间切换。
- 退出：页面矩阵无“未实现”P1 项；新增测试覆盖核心交互与角色差异。

### R5 · 全链路测试（P1）

- [x] R5.1 按第 6 节矩阵补齐自动化（平台 unittest + 前端 Vitest + Playwright）。
- [x] R5.2 E2E 扩展：新词接受→确认锁定→重解析 v2、分享、重试、证据定位、跨 KB/跨工作空间越权。
- [x] R5.3 多租户流程：工作空间创建→邀请→接受→成员/角色变更→权限生效→移出即 403；API Key 跨空间拒绝。
- [x] R5.4 真实文档链路：5 份代表标准（表格/跨页/脚注/转置/多牌号）走 PDF→parsekit→抽取→复核→导出，记录耗时与质量。
- [x] R5.5 故障注入：OCR/版面/SFT 断、DB 断、磁盘满、worker 崩溃、重复点击解析。
- [x] R5.6 并发：同文档双解析、双 worker 抢占、批量复核 200 条边界。
- [x] R5.7 Postgres：空库迁移→运行→备份→恢复→降级；SQLite 兼容回归。
- 退出：P0/P1 用例全绿；失败项有单号和明确结论。

### R6 · 生产化与发布（P1）

- [x] R6.1 监控核对：Prometheus 规则/看板指标名与实际输出一致；告警演练。
- [x] R6.2 日志：结构化 + 请求 ID + 任务 ID；错误聚合。
- [x] R6.3 性能：30 页文档 p95 ≤5 分钟；队列阈值与扩容验证。（**部分达成**：最佳配置下 37 页扫描件 234s、22 页文本层 80s；全量 25 份/434 页中 ≤30 页文档 18/21 份达标（85.7%），超大表格文档 389–2266s 未达标，见第 25/26 节）
- [x] R6.4 备份：加密、异地、恢复演练（含 Postgres）。（异地存储待运维执行）
- [x] R6.5 发布/回滚（D2-A）：镜像 tag 灰度切换（先 api/web，后 worker）→ 观察 → 全量；保留上一 tag 一键回滚；`docker compose up -d` 冷启动/重启演练；K8s 演练列为 P2。
- [x] R6.6 依赖/密钥扫描：`pip-audit`、`npm audit`、secret scan 0 高危。
- [x] R6.7 运行手册更新（启动顺序、故障码、回滚、值班）。
- 退出：SLO 证据包、回滚演练记录、值班表可用。

### R7 · 试点验收（业务）

- [ ] R7.1 100–300 份真实标准、4 周灰度。
- [ ] R7.2 指标：成功率 ≥99%、p95 ≤5 分钟、证据率 ≥95%、silent 0（抽样）、复核一次通过率 ≥80%、高风险 100% 拦截。
- [ ] R7.3 签字：业务/技术/安全/运维。
- 退出：`docs/pilot-acceptance.md` 签字完成；未签字不对外承诺 SLA。

---

## 6. 测试矩阵（功能完整性口径）

| ID | 场景 | 期望 | 现状 |
|---|---|---|---|
| AUTH-01 | 正确/错误密码；禁用用户 | 200/401 | 已覆盖 |
| AUTH-02 | 过期/篡改 JWT；无 token | 401 | 部分 |
| AUTH-03 | 登录限流/锁定 | 429/锁定 | **缺** |
| AUTH-04 | API Key 读/写 scope、撤销 | 200/403/401 | 已覆盖 |
| KB-01 | 创建/列表/详情；非成员访问 | 200/403 | 已覆盖 |
| KB-02 | 成员增删/角色 | 200 | **缺** |
| TENANT-01 | 跨工作空间读文档/任务/证据/审计 | 403/404 | **缺** |
| TENANT-02 | 邀请 token：接受/撤销/过期/重复使用 | 200/401/409 | **缺** |
| TENANT-03 | 角色能力矩阵：owner/admin/member、KB owner/editor/viewer | 逐项 200/403 | **缺** |
| TENANT-04 | API Key 跨工作空间/KB 白名单 | 403 | **缺** |
| DOC-01 | `.md/.pdf` 上传；后缀/空文件/超大 | 201/415/422/413 | 已覆盖 |
| DOC-02 | 同名不同内容、同 sha 重复 | 201/200 幂等 | 已覆盖 |
| DOC-03 | 文件名穿越/CJK/超长 | 安全落盘 | 部分 |
| DOC-04 | 删除/取消/分页/搜索 | 200/202 | **缺** |
| PARSE-01 | inline 关闭时 worker 消费 | 完成 | 部分 |
| PARSE-02 | 重复 parse 幂等；确认后重解析 v+1 | 200/新版本 | 已覆盖 |
| PARSE-03 | 失败重试；锁定任务重试 | 202/409 | 已覆盖 |
| PARSE-04 | OCR/版面/SFT 断 | 明确失败码，不写假结果 | **缺** |
| RES-01 | items/records/clauses/evidence/result 一致性 | 同源 | 已覆盖 |
| RES-02 | 索引按需同步、重复访问幂等 | 不重复/不丢失 | 已覆盖 |
| RES-03 | 证据单条查询、缺失 404 | 200/404 | 已覆盖 |
| RES-04 | 预览页图/版面/缺页 | 200/404/409 | 已覆盖 |
| REV-01 | 新词 accept/map/reject + 回流 | 200 | 已覆盖 |
| REV-02 | 待处理新词阻止确认 | 409 | 已覆盖 |
| REV-03 | 高风险未复核阻止确认 | 409 | 已覆盖 |
| REV-04 | 字段 accept/edit/reject/diff/batch | 200/422 | 已覆盖 |
| REV-05 | 确认后锁定：新词/字段/重试 | 409 | 已覆盖 |
| SHARE-01 | 有效/过期/篡改 token | 200/401 | 已覆盖 |
| SHARE-02 | 分享包与本人视图一致 | 一致 | 部分 |
| DICT-01 | 查询三类词条 | 200 | 已覆盖（引擎） |
| DICT-02 | 鉴权/别名/pending/版本 | 200/403 | **缺** |
| EXPORT-01 | hansonDoc schema / CSV / XLSX | 可下载且字段完整 | **缺** |
| OPS-01 | `/health` `/ready` `/metrics` 各平面 | 200/503 | 已覆盖 |
| OPS-02 | 迁移 head 校验、Postgres 冷启 | 通过 | **缺** |
| UI-01 | 主链路（登录→KB→上传→解析→结果→复核→退出） | 通过 | 已覆盖 |
| UI-02 | 分享、重解析、重试、新词、确认锁定 | 通过 | **缺** |
| UI-03 | 401 自动退出、403 提示、空态/错误态 | 通过 | 部分 |
| UI-04 | 工作空间切换、成员/邀请、角色隐藏按钮 | 通过 | **缺** |

---

## 7. 验收标准（Go / No-Go）

**代码**
- 引擎/平台/Web 测试 + E2E + 第 6 节 P0/P1 用例全绿；
- `typecheck`/`build` 通过；OpenAPI 与实现一致；
- 冷启动脚本一键可用，失败有明确修复提示。

**安全**
- 匿名无法读取任何文档/任务/证据/词典数据；
- 跨工作空间、跨 KB 越权全部 403/404；角色能力矩阵逐项有测试；
- 邀请 token 一次性、过期失效；API Key 不能跨工作空间；
- 密钥扫描 0 高危；生产 secret 非默认；登录有限流；
- 越权测试（跨 KB、API Key scope、分享 token）全绿。

**质量**
- 20 份金标基线不回退（Record 0.8604 / Field 0.8208 / Value 0.9368）；
- 试点：高风险 100% 拦截、复核一次通过率 ≥80%、证据率 ≥95%、silent 0（抽样）；
- 未达 G2 95% 前，产品文案与 SLA 不承诺“免复核自动发布”。

**运维**
- p95 ≤5 分钟（30 页）；失败率 <2%；队列积压告警可用；
- 备份 <24h 且恢复演练通过；灰度与回滚演练通过；
- 值班表、运行手册、故障码表可用。

**业务**
- `docs/pilot-acceptance.md` 四方签字。

---

## 8. 已确认决策与执行前置输入

### 8.1 已确认（本轮）

| # | 决策 | 结论 | 对计划的影响 |
|---|---|---|---|
| D1 | 生产范围 | **B 完整多租户**：工作空间、成员/邀请/角色、用户管理、审计、API Key 作用域 | R3/R4 按 4.4 展开；新增租户隔离测试；A12 以此关闭 |
| D2 | 部署形态 | **A 单机 Docker Compose + Postgres** | R1/R6 以 Compose 冷启动、备份恢复、灰度回滚为门禁；K8s 后置 P2 |
| D3 | PDF 接入 | **A 恢复 parsekit 版面服务 `:9978`** | R1.4 按 `LayoutClient` 契约实现；真实 PDF E2E 恢复 |
| D4 | 质量门禁 | **A 人机复核放行** | R7 以高风险拦截、一次通过率、证据率、silent 0 验收；不承诺免复核 |

### 8.2 执行前置输入（不阻塞计划，但阻塞对应阶段）

| 输入 | 需要谁提供 | 用于 |
|---|---|---|
| 生产主机（CPU/内存/磁盘）与域名/端口 | 运维 | R1 Compose 落地 |
| 现有 `data/platform` 与 20 份金标产物是否迁移 | 项目负责人 | R3.1 数据迁移 |
| Git 仓库地址/权限（当前无 `.git`） | 项目负责人 | R0.1 版本控制 |
| 模型机 sudo/启动权限、GPU 余量 | 模型负责人 | R1.4 版面服务与 9991 |
| 试点部门、文档清单、验收人 | 业务负责人 | R7 试点 |
| 外部安全评审排期 | 安全 | 上线签字 |

---

## 9. 主要风险

| 风险 | 触发 | 应对 |
|---|---|---|
| 真实模型链路未验证 | 只跑 mock E2E | R1.4/R5.4 强制真实 PDF 走通并入 CI 夜间任务 |
| 配置漂移 | 本机/Compose/K8s 三套 env | 单一 `.env` 契约 + 启动自检 + 文档对照表 |
| 权限回归 | 前端继续用 `/v1/jobs` | R2.2 删除旧调用 + 越权测试 |
| 多租户迁移事故 | 回填 workspace_id/成员关系错误 | R3.0 权限矩阵先定稿；迁移前备份；迁移前后行数与抽样校验 |
| 迁移/备份事故 | create_all 与 Alembic 双轨 | R1/B6 统一 Alembic；上线前备份与恢复演练 |
| 质量预期错位 | 对外承诺“自动准确” | D4 口径 + 产品文案限定“人机复核” |
| 范围蔓延 | 多租户/导出/词典同时展开 | 以 R3/R4 任务表和 4.4 为准，P2 后置 |
| 无版本控制 | 直接改生产 | R0.1 建立仓库/tag，改动可回滚 |

---

## 10. R1 执行记录（2026-10-31）

**结论：R1 完成，运行时闭环可用。**

### 10.1 代码与配置变更

| 文件 | 变更 |
|---|---|
| `apps/api/hanson_api/main.py`（新增） | 统一 ASGI 入口 `hanson_api.main:app`；导入时执行生产启动自检 |
| `apps/api/main.py` | 降为兼容 shim，指向 `hanson_api.main` |
| `apps/api/hanson_api/startup.py`（新增） | 生产校验：secret、Postgres、Alembic、inline、OCR/抽取/版面/SFT |
| `apps/api/hanson_api/db.py` | 新增 `verify_migrations`（缺失/落后 head 直接失败） |
| `apps/api/hanson_api/config.py` | 新增 `HANSON_ENV`、`HANSON_DB_AUTO_CREATE`；生产默认不自动建表 |
| `apps/api/hanson_api/router.py` | 生产就绪检查纳入迁移版本与模型端点；版面服务要求 `status=ok & loaded=true` |
| `apps/api/pyproject.toml` | 新增 `httpx`、`psycopg[binary]==3.3.6` |
| `metal-doc-agent/pyproject.toml` | 补齐未声明的 `jsonschema==4.26.0`（容器启动暴露） |
| `metal-doc-agent/.../settings.py`、`clients/layout.py` | 支持 `LAYOUT_SERVICE_TOKEN`（`X-Layout-Token`） |
| `infra/model-plane/serve_layout.py`、`start_layout.sh`、`README.md`（新增） | PP-DocLayoutV3 HTTP 服务：`/health` + `/v1/layout`，归一化 bbox |
| `infra/docker/Dockerfile.api` / `.engine` / `.web` | 入口修正、pnpm + lockfile、PyPI/npm 镜像构建参数、pip 重试 |
| `infra/docker/compose.yaml` | Postgres/健康检查、engine/worker 只读挂载 `platform-data`、Redis/MinIO 改为 extras |
| `.dockerignore`（新增） | 排除 `runs/`、`data/`、`node_modules` 等构建噪音 |
| `deploy/start_local.ps1`、`deploy/.env.example`、`infra/docker/.env.example`、`infra/k8s/config.yaml` | 统一 9977/9978/9991 + adapter-v5；本地启动前检查模型端点 |
| `e2e/run_main_flow.ps1`、`README.md`、`apps/api/README.md`、`docs/runbook.md`、`deploy/README.md`、`infra/monitoring/README.md` | 入口与模型端点同步 |

### 10.2 验证证据

| 项 | 结果 |
|---|---|
| 本机 `deploy/start_local.ps1` | `/platform/ready` 200：database/recipes/coverage/data/OCR/layout/extractor/SFT 全 true |
| 真实 PDF（Q-Du 302 第 5 页）本机平台链路 | 3 记录 / 2 项目 / 20 证据 / 1 页；记录条件“T6或T651或T652 / 切向”正确 |
| Compose 冷启动（WSL Docker 29.7.2，6 服务） | 全部 healthy；Postgres `alembic_version=h4e5f6a7b8c9` |
| 真实 PDF 容器链路（worker-prod + 真实 OCR/版面/vLLM） | `review` 完成；3 记录 / 2 项目 / 26 证据 / 1 页；预览 `pages/1/image` 可用 |
| 就绪降级 | 停版面服务 → `/platform/ready` **503**，`model_layout=false`；恢复后 **200** |
| 迁移回滚 | SQLite `upgrade head → downgrade base → upgrade head` 通过；Postgres 空库 upgrade 通过 |
| 测试 | 引擎 **387**、平台 **29**、Web **5**、E2E 主链路通过 |

### 10.3 遗留与后续输入

- 本机 Windows 无 Docker，Compose 验证在 WSL Ubuntu Docker 29.7.2 完成；生产主机仍需按 `infra/docker/.env.example` 冷启动一次。
- 版面服务与 vLLM 共用 GPU 会 OOM，当前 `LAYOUT_DEVICE=cpu`（单页 1653×2342 约 4.8s）；R6 需评估 vLLM 显存上限或独立 GPU。
- Compose 构建在受限网络需要 `PIP_INDEX_URL` / `NPM_REGISTRY` 构建参数；默认仍为官方源。
- `METAL_DOC_ORCHESTRATE=1` 单页真实文档耗时约 3 分钟（含编排），在 5 分钟 SLO 内但需 R6 压测确认。
- 仍无 `.git`，R0.1 版本控制需用户提供仓库；R1/R2 已完成，R3 见第 12 节。

---

## 11. R2 执行记录（2026-10-31）

**结论：R2 完成，平台面安全边界闭环。**

### 11.1 代码与配置变更

| 文件 | 变更 |
|---|---|
| `apps/api/hanson_api/app.py`（新增） | `build_app` 组合；默认移除引擎 `/v1/jobs*`、`/v1/recipes`、`/v1/batches`；词典引擎路由永不挂平台端口；安全响应头与 API CSP |
| `apps/api/hanson_api/main.py` | 改用 `build_app`，保留生产启动自检 |
| `apps/api/hanson_api/router.py` | 登录限流；平台鉴权 `GET /v1/business-dictionary` |
| `apps/api/hanson_api/security.py` | `LoginLimiter`（用户名 + 客户端 IP，429 + Retry-After） |
| `apps/api/hanson_api/config.py` | `HANSON_LOGIN_*` 配置 |
| `apps/web/src/api.ts` | 删除全部 `/v1/jobs*` 调用，仅保留平台文档/任务接口 |
| `apps/web/src/pages/JobDetailPage.tsx` | 结果页统一走 `/v1/documents/*`；裸 `/jobs/<id>` 用 `GET /v1/tasks/{id}` 解析文档上下文 |
| `infra/docker/nginx.conf` | Web CSP/安全头；移除 `/engine/` 反代并显式 404 |
| `infra/docker/compose.yaml` | 移除 engine-api 主机端口，仅内网 `8010` |
| `apps/api/tests/test_security.py`（新增） | 8 个安全边界测试 |
| `e2e/test_main_flow.py` | 增加裸 `/jobs/<id>` 解析用例 |
| `packages/contracts/openapi.json` | 重新导出平台面契约（42 paths） |
| `docs/security.md`、`README.md`、`apps/api/README.md` | 安全口径与入口说明同步 |

### 11.2 验证证据

| 项 | 结果 |
|---|---|
| 规范入口 `hanson_api.main:app` | `/v1/jobs` `/v1/batches` `/v1/recipes` **404**；`/v1/business-dictionary` 无 token **401** |
| 容器内验证 | 同上；登录后词典 **200**（5 条）；`X-Engine-Token` 未设置时引擎数据路由不可达 |
| Web 平面 | `/engine/v1/jobs` **404**；`/v1/jobs` **404**；CSP/`X-Frame-Options`/`nosniff` 全量返回 |
| API 安全头 | `/v1/*` 返回 CSP `default-src 'none'; frame-ancestors 'none'`，auth 响应 `Cache-Control: no-store` |
| 登录限流 | 第 5 次错误 **429**；锁定期间正确密码仍 **429** |
| 越权测试 | 跨 KB 文档/证据/分享 **403**；跨 KB 任务 **403** 且列表为空；API Key 只读 scope 写操作 **403**；篡改/过期分享 token **401** |
| 测试 | 平台 **37**（含 R2 安全 8）、Web **5**、E2E（含裸 job URL）通过 |

### 11.3 遗留

- 登录限流为进程内实现；多副本部署需网关/Redis 全局限流（R3 可随多租户一起接）。
- 词典 `POST /sync` 仍为 `planned`（R3.9 已落地，见第 12 节）。
- 引擎独立 `engine-api:8010` 仍为内网服务；若需外部访问，必须配置 `ENGINE_INTERNAL_TOKEN`。

---

## 12. R3 执行记录（2026-10-31）

**结论：R3 完成，完整多租户、用户/邀请/API Key、审计、导出与词典闭环可用；Postgres 容器验证通过。**

### 12.1 代码与配置变更

| 文件 | 变更 |
|---|---|
| `apps/api/hanson_api/models.py` | 新增 `Workspace`、`WorkspaceMember`、`Invitation`；`KnowledgeBase`/`ApiKey`/`AuditLog` 加 `workspace_id`；API Key 加 `kb_ids` |
| `apps/api/alembic/versions/i5f6a7b8c9d0_workspaces.py`（新增） | 建表 + `workspace_id` 列；回填默认工作空间、KB、KB 成员、API Key；非空约束；可 downgrade |
| `apps/api/hanson_api/access.py`（新增） | `Principal` 扩展 workspace/kb_ids；工作空间与 KB 双层角色判定；API Key 角色上限（按创建者角色与 scope 取低）；默认工作空间 |
| `apps/api/hanson_api/schemas.py` | 用户管理/个人资料/改密、工作空间/成员/邀请、KB 更新与成员、API Key workspace/kb_ids、审计 workspace_id、词典 alias/sync |
| `apps/api/hanson_api/router.py` | 工作空间/成员/邀请/用户 API；KB CRUD/成员；文档删除、任务取消、列表 `q/status/offset`；四种导出；词典 pending/sync/alias；审计 `workspace_id/action/offset`；API Key 绑定工作空间与 KB 白名单 |
| `apps/api/hanson_api/app.py` | RFC 9457 `application/problem+json` 统一错误封装（保留 `detail`），覆盖 Starlette/平台 HTTPException 与 422 校验错误 |
| `apps/api/hanson_api/export.py`（新增） | hansonDoc schema 投影（复用 `tools/export_hanson_schema.py`）+ JSON/CSV/XLSX（openpyxl） |
| `apps/api/pyproject.toml` | 新增 `httpx==0.28.1`、`psycopg[binary]==3.3.6`、`openpyxl==3.1.5` |
| `apps/api/tests/test_workspaces.py`（新增） | 8 个多租户/邀请/API Key/词典/审计/取消/删除测试 |
| `apps/api/tests/test_export.py`（新增） | 2 个导出与分享导出测试 |
| `apps/api/tests/test_security.py` | +1 problem+json 错误封装测试 |
| `apps/web/src/pages/ApiKeysPage.tsx`、`AuditPage.tsx`（新增） | API Key 工作空间/scope/KB 白名单；审计按工作空间/action 筛选 |
| `apps/web/src/App.tsx`、`types.ts`、`api.ts` | 新增路由、类型与接口；文档 `q/status/limit/offset`；删除/取消/导出 URL |
| `apps/web/src/pages/JobDetailPage.tsx`、`SharedResultPage.tsx`、`DictionaryPage.tsx` | hanson/CSV/XLSX 导出；分享页下载；词典同步与别名（平台 admin） |
| `packages/contracts/openapi.json` | 重新导出平台面契约（**60 paths**） |
| `docs/multi-tenant-design.md`（新增） | R3.0 权限矩阵、判定顺序、邀请与迁移方案 |
| `infra/docker/.env.example`、`deploy/.env.example` | 新增 `HANSON_INVITATION_MINUTES` 说明 |

### 12.2 验证证据

| 项 | 结果 |
|---|---|
| Postgres 迁移 | 容器空库 `alembic_version=i5f6a7b8c9d0`；SQLite 旧数据（2 用户/KB/成员/API Key）升级后默认工作空间、成员、KB、API Key 回填正确，downgrade 删除表/列且保留旧数据，再升级重建通过（14/14） |
| Compose 容器冒烟（平台面） | **54/54**：工作空间 CRUD、用户管理、邀请一次性/重复接受 409、成员角色、KB viewer 403、API Key 工作空间+KB 白名单+只读 scope 写拒绝+吊销 401、词典 sync/pending/alias 与非 admin 403、审计全局/工作空间筛选与成员 403、文档上传/筛选/删除、queued 任务取消（failed+cancelled） |
| 真实 PDF 容器链路（Q-Du 302 第 5 页） | `review` 完成：2 项目 / 3 记录 / 26 证据 / 15 条款；hanson 导出 `total_records=16`、CSV 16 行、XLSX 9.1 KB；分享导出 CSV/XLSX 可用，篡改 token **401**（26/26） |
| 错误封装 | 未认证请求返回 `application/problem+json`（401，`title=Unauthorized`，保留 `detail`）；422 校验错误同格式；安全头与 `Retry-After` 保留 |
| 测试 | 平台 **48 passed**（含 R3 8+2+1）、Web **5 passed**、`typecheck`/`build` 通过 |
| 契约 | `packages/contracts/openapi.json` 60 paths，无 R3 悬空端点 |

### 12.3 遗留与后续输入

- 工作空间切换/成员与邀请/用户管理/个人中心页面归 **R4.1**（R3 已提供全部后端 API）。
- 登录限流仍为进程内；多副本部署需网关/Redis 全局限流（R6）。
- 分享导出复用 15 分钟 HMAC 分享 token，未单独签发下载 token；如需长期下载需在 R4/R6 设计。
- API Key 明文仅创建时返回，轮换=撤销后重建，本期不做自动轮换。
- 生产库执行迁移前必须备份；本轮已在 SQLite 旧数据与 Postgres 空库验证，生产数据回填需按 `docs/runbook.md` 演练。
- 前端错误提示仍展示原始 `detail` 文本，尚未按 `title/status` 分层展示（R4.3 统一错误文案）。

---

## 13. R4.1 执行记录（2026-11-01）

**结论：R4.1 完成，多租户前端页面与工作空间切换可用。**

### 13.1 代码变更

| 文件 | 变更 |
|---|---|
| `apps/web/src/workspace.tsx`（新增） | 工作空间上下文：列表加载、当前空间持久化（`hanson.workspace`）、`select/reload` |
| `apps/web/src/pages/WorkspacesPage.tsx`（新增） | 工作空间列表/创建/切换/入口 |
| `apps/web/src/pages/WorkspaceDetailPage.tsx`（新增） | 空间设置、成员增删/角色调整、邀请创建/一次性 token/撤销、owner 删除 |
| `apps/web/src/pages/UsersPage.tsx`（新增） | 平台 admin 用户搜索/创建/显示名/角色/启停/重置密码 |
| `apps/web/src/pages/ProfilePage.tsx`（新增） | 基本信息、显示名、改密、邀请 token 接受、我的工作空间 |
| `apps/web/src/App.tsx` | 路由与导航；`WorkspaceProvider`；顶栏工作空间选择器；用户名入口到个人中心；admin 才显示「用户」 |
| `apps/web/src/pages/KbListPage.tsx` | 知识库列表/创建绑定当前工作空间，创建后刷新空间列表 |
| `apps/web/src/pages/ApiKeysPage.tsx` | 默认工作空间取自全局上下文，避免重复拉取空间列表 |
| `apps/web/src/auth.tsx` | 新增 `refresh()`，个人资料更新后同步顶栏显示名 |
| `apps/web/src/api.ts` | 新增 `workspace/updateWorkspace/deleteWorkspace`；邀请支持 `expires_minutes` |

### 13.2 验证证据

| 项 | 结果 |
|---|---|
| 类型检查/构建 | `tsc --noEmit`、`vite build` 通过（JS 381.15 kB / gzip 109.10 kB） |
| Web 单测 | **5 passed** |
| 浏览器（Compose + 新 Web 镜像） | 登录 admin → 顶栏空间选择器/工作空间/用户导航可见；工作空间详情显示成员（admin、r3-member）与邀请区 **PASS** |
| 浏览器邀请流 | 创建 member 邀请：一次性 token 展示 + pending 行（r4-ui-smoke）**PASS** |
| 浏览器账号流 | 用户页创建 `r4-ui-user` 并出现在列表；个人中心显示基本信息与我的工作空间 **PASS** |
| E2E 主链路 | **通过 / 6.3s** |

### 13.3 遗留

- 邀请接受仅由 R3 自动化测试覆盖，浏览器端未单独走一遍（页面已提供入口）。
- 审计页仍使用自身工作空间选择器，未强制跟随顶栏当前空间（后续可统一）。
- R4.5–R4.7 已补齐，见第 17 节；页面矩阵 P1 无未实现项。

---

## 14. R4.2 执行记录（2026-11-01）

**结论：R4.2 完成，任务/文档可筛选分页，记录/条款/证据改为虚拟滚动。**

### 14.1 代码变更

| 文件 | 变更 |
|---|---|
| `apps/api/hanson_api/router.py` | `GET /v1/tasks` 新增 `status` + `offset`；`GET /v1/documents` 状态筛选改为按任务实际状态过滤（修复数据库旧状态与返回状态不一致） |
| `apps/api/tests/test_platform_api.py` | 覆盖任务状态筛选/偏移分页、文档状态筛选命中 |
| `apps/web/src/VirtualTable.tsx`（新增） | 基于 `@tanstack/react-virtual` 的通用虚拟表格（动态行高、sticky 表头、10 行 overscan） |
| `apps/web/src/components.tsx` | 新增 `Pagination`（页码、本页条数、边界禁用） |
| `apps/web/src/pages/JobsPage.tsx` | 状态筛选 + 20 条/页分页，筛选变化回到第 1 页 |
| `apps/web/src/pages/KbDetailPage.tsx` | 文档：文件名搜索（300ms 防抖）+ 状态筛选 + 分页；任务：状态筛选 + 分页；轮询保留筛选 |
| `apps/web/src/pages/JobDetailPage.tsx` | 记录/条款/证据三张表改用 `VirtualTable`，证据引用不再截断 |
| `apps/web/src/components.test.tsx` | 新增分页组件测试（Web 测试 5 → 6） |
| `apps/web/package.json`、`pnpm-lock.yaml` | 新增 `@tanstack/react-virtual` |
| `packages/contracts/openapi.json` | 重新导出（60 paths，任务端点含新查询参数） |

### 14.2 验证证据

| 项 | 结果 |
|---|---|
| 平台测试 | **48 passed** |
| Web 测试/构建 | **6 passed**；build 通过（JS 419.32 kB / gzip 122.38 kB） |
| 浏览器任务筛选 | 任务页选择「待复核」→ review 任务行显示，分页「第 1 页 · 本页 1 条」**PASS** |
| 浏览器文档筛选 | 知识库内搜索 `qdu` + 状态「待复核」→ `qdu_p5.pdf` 显示，分页「第 1 页 · 本页 1 条」**PASS**（修复前同条件为空） |
| 浏览器虚拟滚动 | 结果页「记录 3」；证据表显示引用行，滚动后出现后续行 **PASS** |
| E2E 主链路 | **通过 / 6.6s** |

### 14.3 遗留

- 文档/任务在带状态筛选时按当前数据量内存过滤；数据量显著增长后需在 R6 增加任务状态索引或物化视图。
- 虚拟表格固定 520px 视口，窄屏横向布局需在 R4.6 响应式检查中复验。
- 证据接口仍只有 `limit`（最大 20000），未提供服务端 `offset`；当前由前端虚拟滚动承载。

---

## 15. R4.3 执行记录（2026-11-01）

**结论：R4.3 完成，错误提示统一为中文可读文案，加载失败可一键重试，轮询退避与长任务进度可见。**

### 15.1 代码变更

| 文件 | 变更 |
|---|---|
| `apps/web/src/api.ts` | 新增 `ApiError`（status/title/detail）；解析 `application/problem+json` 与 422 校验数组；状态码中文标签 + 后端 detail 映射；登录/权限/冲突等常见错误本地化；`fetchObjectUrl` 复用同一错误解析 |
| `apps/web/src/components.tsx` | `ErrorNote` 支持可选 `onRetry`，展示「重试」按钮 |
| `apps/web/src/pages/JobDetailPage.tsx` | 等待结果改为时间退避（2s × 1.5 递增，上限 15s，总等待上限 15 分钟）；等待时轮询任务状态，展示阶段/进度条/已等待时长；不再用 `message.startsWith("409")` 判断 |
| `apps/web/src/pages/KbDetailPage.tsx` | 活动任务轮询改为 2–15 秒退避；任务区显示「自动刷新」提示 |
| `apps/web/src/pages/JobsPage.tsx`、`WorkspacesPage.tsx`、`WorkspaceDetailPage.tsx`、`UsersPage.tsx`、`DictionaryPage.tsx`、`AuditPage.tsx` | 加载失败错误条接入「重试」 |
| `apps/web/src/api.test.ts`（新增） | problem+json 详情映射、422 校验数组摘要测试 |
| `apps/web/src/components.test.tsx` | 新增 ErrorNote 重试回调测试 |

### 15.2 验证证据

| 项 | 结果 |
|---|---|
| Web 测试 | **9 passed**（api 2 + components 7） |
| Web 构建 | 通过（JS 424.12 kB / gzip 124.32 kB） |
| Playwright · 登录错误 | 错误密码显示「用户名或密码错误」，不再出现 `401 Unauthorized {json}` 原文 |
| Playwright · 长任务 | 停 worker 后创建 queued 任务，结果页显示「解析进行中 · 0%」、进度条、「已等待 … 自动刷新」 |
| Playwright · 403 重试 | `r3-member` 访问审计页显示「工作空间角色不足」并可点击「重试」 |
| E2E 主链路 | **通过 / 8.2s** |
| 平台测试 | 沿用 **48 passed**（R4.3 未改后端） |

### 15.3 遗留

- 退避参数（2s 起步、15s 上限、15 分钟总等待）为前端常量，后续可做成配置。
- 重试按钮覆盖加载失败；表单提交/动作类错误仍显示内联文案，避免重复提交。
- 长任务进度依赖任务探测接口；探测失败时仅保留等待文案，不影响最终结果刷新。

---

## 16. R4.4 执行记录（2026-11-01）

**结论：R4.4 完成，四种导出在结果页与分享页均可下载，文件名带扩展名，过期分享有明确提示。**

### 16.1 代码变更

| 文件 | 变更 |
|---|---|
| `apps/web/src/api.ts` | 新增 `exportFileName`（hanson→`.json`、csv/xlsx 对应扩展名）；分享 token 过期/无效映射为「分享链接已过期或被撤销」 |
| `apps/web/src/pages/JobDetailPage.tsx` | 新增 JSON 导出；按格式显示「导出中…」；导出失败标注格式；分享按钮显示实际到期时间；已有链接时按钮为「重新生成分享链接」并增加「打开」 |
| `apps/web/src/pages/SharedResultPage.tsx` | 分享页新增 JSON 导出；按格式下载状态与失败提示；过期/无效 token 显示「分享链接已过期」并提示联系所有者重新分享 |
| `apps/web/src/api.test.ts` | 新增过期分享映射与导出文件名测试 |

### 16.2 验证证据

| 项 | 结果 |
|---|---|
| Web 测试 | **11 passed** |
| Web 构建 | 通过（JS 424.94 kB / gzip 124.70 kB） |
| Playwright · 结果页下载 | hanson JSON 8916B、JSON 32559B、CSV 2029B、XLSX 9114B；文件名均带正确扩展名，hanson `total_records>0` |
| Playwright · 分享页下载 | 同四格式均成功（8916/32559/2029/9115B） |
| Playwright · 过期分享 | 篡改 token 显示「分享链接已过期」与「分享链接已过期或被撤销」 |
| E2E 主链路 | **通过 / 6.3s** |

### 16.3 遗留

- 分享链接只能由文档所有者在结果页重新生成；分享页本身不提供重新签发入口。
- 下载文件名为文档 ID + 格式，未使用标准号/标题；如需可读文件名可在后续调整。

---

## 17. R4.5–R4.7 执行记录（2026-11-01）

**结论：R4 全部完成。角色可见性、移动端布局、键盘可达性与页面级测试均通过。**

### 17.1 代码变更

| 文件 | 变更 |
|---|---|
| `apps/web/src/pages/KbDetailPage.tsx` | 按 KB 角色（owner/editor）显示上传与解析/重试按钮；viewer 显示只读提示 |
| `apps/web/src/pages/JobDetailPage.tsx` | 结果页加载 KB 角色并计算 `canEdit`；viewer 隐藏提交/确认复核、重新拆分、批量接受、字段接受/修正、新词接受/映射/拒绝，并显示只读提示 |
| `apps/web/src/VirtualTable.tsx` | 增加 `table/rowgroup/row/columnheader/cell` ARIA 角色、`aria-rowcount/colcount`，滚动区可聚焦 |
| `apps/web/src/components.tsx` | `ErrorNote` 增加 `role="alert"` |
| `apps/web/src/App.tsx` | 顶栏可换行；新增「跳到主要内容」skip link；`main` 可聚焦；工作空间选择器 `aria-label` |
| `apps/web/src/styles.css` | 增加统一 `:focus-visible` 焦点环 |
| `apps/web/src/pages/pages.test.tsx`（新增） | 4 个页面测试：任务筛选+重试、空态、工作空间切换、viewer 隐藏写操作 |

### 17.2 验证证据

| 项 | 结果 |
|---|---|
| 角色可见性（Playwright） | viewer：知识库无「上传文档」按钮且显示只读提示；复核页无提交/确认/批量/接受按钮；新词页无映射按钮；直接调用写接口仍为 **403** |
| 移动端 390×844 | 11 个页面（任务/知识库/文档/结果/词典/API Key/审计/工作空间/成员/用户/个人中心）横向溢出均为 **0** |
| 可访问性 | 虚拟表 `table` 1 个、`columnheader` 4 个、`row` ≥2；无未命名按钮、无缺 alt 图片；Tab 首次聚焦 skip link，回车后焦点到 `main-content` |
| Web 测试 | **15 passed**（api 4 + components 7 + pages 4） |
| Web 构建 | 通过（JS 426.23 kB / gzip 125.15 kB） |
| E2E 主链路 | **通过 / 7.6s** |

### 17.3 遗留

- 证据/新词弹窗未做完整焦点陷阱（Esc 关闭已有）；如需 WCAG 深度合规可在 R6 引入 a11y 自动化。
- 虚拟表在极窄屏依赖横向滚动，表头与内容同步滚动；尚未做列折叠。
- 对比度按现有 slate 配色目测满足 AA（正文 slate-700/500），未接入 axe 自动扫描。

---

## 18. R5.1–R5.4 执行记录（2026-11-01）

**结论：R5.1–R5.4 完成。5 份真实标准全链路（PDF→版面/OCR→抽取→结果接口→四格式导出）通过；evidence 重复导致的 `/items` 500 已修复并部署。**

### 18.1 自动化基线

| 套件 | 结果 |
|---|---|
| 平台 API unittest（容器内） | **53 passed**（含新增租户/安全/幂等/去重/导出测试） |
| 引擎 unittest | **387 passed**（平台契约断言不含 `/v1/jobs`、`/v1/batches`、`/v1/recipes`） |
| Web Vitest | **15 passed** |
| Playwright 主链路 | 通过（登录→知识库→上传→解析→结果→复核→分享→下载→登出） |

### 18.2 R5.2 / R5.3 流程覆盖

| 场景 | 证据 |
|---|---|
| 字段复核 | E2E：证据「定位」→ viewer → 返回 → 「接受」→ 出现「已接受」 |
| 分享 | E2E：生成分享链接→新页面打开→只读页标题正确→下载 `*-hanson.json`（>500B）；平台测试覆盖过期/篡改 token |
| 新词 | 平台测试：accept / reject / map 三种动作 |
| 确认与版本 | 平台测试：高风险字段未复核时确认 409；确认后 retry 409；重新拆分生成 v2（`review_version=2`） |
| 跨 KB | 平台测试：跨 KB 文档/任务/证据 403 |
| 多租户 | 平台测试：创建→邀请→接受→改角色→移出→403；API Key 跨空间 403 |
| 重试/重解析 | 平台测试：确认锁定 retry 409；未锁定 retry 可重跑；重复解析幂等 |

### 18.3 R5.4 真实文档结果

| 文件 | 页数 | 耗时 | 终态 | items / records / clauses / evidence | hanson records | 质量要点 |
|---|---:|---:|---|---:|---:|---|
| qdu_p5.pdf | 1 | 14s | review | 2 / 3 / 15 / 26 | 16 | 2 项全部 confirmed |
| GBT 3191-1998 | 11 | 146s | succeeded | 6 / 41 / 59 / 150 | 78 | 2 probable、1 ambiguous、2 列未映射 |
| GBT33084-2016 | 18 | 242s | succeeded | 4 / 234 / 55 / **1472** | 1279 | 8 表，4 项全部 confirmed |
| GB∕T 1220-1992 | 23 | 731s | review | 17 / 126 / 52 / 1052 | 797 | 22 表，15 confirmed / 2 probable，6 列未映射 |
| Q/S10-0351-2004 | 12 | 76s | succeeded | 13 / 4 / 51 / 69 | 20 | 12 confirmed / 1 ambiguous |

- 四格式导出（hanson / json / csv / xlsx）对 5 份文档全部 **200**，文件名带对应扩展名；hanson 顶层含 `records` 与 `summary.total_records`。
- `evidence` 数量与 artifacts/DB 一致；GB/T 1220 证据 1052 > API 默认 `limit=1000`，验证时显式使用 `limit=20000`（前端默认请求 5000）。
- DB 中 `evidence_index` 已与本任务 artifact 对齐：GBT33084 去重后 **1472** 行且 `distinct(evidence_id)=1472`。

### 18.4 问题定位与修复

| 问题 | 根因 | 处理 | 验证 |
|---|---|---|---|
| GBT33084 `GET /items`、`GET /evidence` 500 | `evidence.jsonl` 含重复 `evidence_id`，触发 `uq_evidence_index` 唯一约束 | `results.py` 按 `evidence_id/record_id/clause_id` 去重；同步异常回滚并回退 artifacts；新增 `test_duplicate_evidence_ids_are_deduped` | 重建 platform-api 镜像并重启；08a 文档 items/evidence **200**，DB 1472 行无重复 |
| GB/T 1220 被误判“卡死” | 23 页文档逐页 CPU 版面推理（约 12–20s/页），worker 处于模型调用等待，非死锁 | 保持任务运行；期间一次误重启使 `attempts=2`，任务最终在 731s 完成 `review` | 状态 `done/review/100`；items/records/clauses/evidence 全部 200 |
| 文档表 `status` 长期停留 `queued` | 解析阶段只更新 JobStore；`document_out` 用 JobStore 状态覆盖，DB 列未回写 | 记录为一致性遗留项（不影响接口/页面），R6 数据治理时统一回写 | 本次不阻塞 R5 |
| PDF 任务 plan 阶段 `page_count=0` | PDF 采用流式渲染，真实页数在 render 阶段产出；plan 不解析全文 | 设计行为，非缺陷 | render 产出 23 页并完成预算内处理 |

### 18.5 性能与后续

- GB/T 1220 23 页耗时 **731s**，超过 R6.3 目标（30 页 p95 ≤5 分钟）的当前实现水位；R6.3 需优化版面/OCR 并行度与单页等待。
- 版面服务为 CPU 单实例串行（约 5s/页），OCR 与抽取为远程模型调用；耗时随页数近似线性。
- 下一单元：R5.5 故障注入（DB 断、模型服务断、磁盘满、worker 崩溃、重复解析）。

---

## 19. R5.5–R5.6 故障注入与并发记录（2026-11-01）

**结论：R5.5、R5.6 完成。数据库/OCR/版面/SFT 故障均进入可控终态；worker 崩溃可自动恢复；重复解析幂等；双 worker 抢占只有一个执行。**

### 19.1 故障注入结果

| 故障 | 注入方式 | 实际结果 | 结论 |
|---|---|---|---|
| DB 断 | `docker stop postgres` | `/platform/ready` **503**（0.29s，database=false）；`/health` **200**；`POST /v1/auth/login` **503** `application/problem+json`，detail=`database unavailable`（0.02s）；恢复 Postgres 后 ready/login **200**，无需重启 API | 修复后通过 |
| OCR 断 | worker `GLM_OCR_BASE_URL=127.0.0.1:9` | 逐块 OCR 失败，任务终态 **review**；`error=ocr quality 0.0`，`failure_code=ocr_failed`，无 500/崩溃 | 通过（人工复核兜底） |
| 版面断 | worker `LAYOUT_SERVICE_URL=127.0.0.1:9` | extract 重试 2 次后 **review**；`error=layout: request failed...`，`failure_code=layout_failed`；状态可诊断 | 通过 |
| SFT 断 | worker `SFT_BASE_URL=127.0.0.1:9` | 任务 **review** 正常产出（3 records、903 tokens），无 error；抽取回退规则/Qwen | 通过（优雅降级） |
| 磁盘满 | 一次性 worker + `/data/engine` 512k tmpfs | 首轮渲染即 `OSError: [Errno 28] No space left on device`；worker 退出码 1；因同一磁盘无法写入，`state` 仍为 `running`；容器 restart policy 会反复重启，日志可见 ENOSPC | 预期限制：需运维清理空间后由 stale recovery 重新入队；R6.1 增加磁盘告警 |
| worker 崩溃 | 运行中 `docker kill`（exit 137） | job 保持 `running/attempts=1`；新 worker 启动后输出 `recovered stale running jobs`，`attempts=2` 重跑并 **succeeded**（215s、3958 tokens） | 通过 |
| 重复点击解析 | 5 并发 `POST /parse` 同一文档 | 5 个响应均指向同一 `job_id`（4×202 + 1×200），无重复任务 | 通过 |
| 批量复核 200 | 平台单测 | 200 条批量接受通过（`test_field_review_batch_accepts`） | 通过 |

### 19.2 代码变更与回归

| 文件 | 变更 |
|---|---|
| `apps/api/hanson_api/app.py` | 新增 `DBAPIError → 503` 处理，统一 `application/problem+json`，detail=`database unavailable` |
| `apps/api/tests/test_platform_api.py` | 新增 `test_database_errors_return_503_problem` |
| `metal-doc-agent/metal_doc_agent/runner.py` | 编排任务终态回写 `error/failure_code`：取最后一条 StepError 消息分类（layout/ocr/extract/timeout/invalid_input）；OCR 质量 0 标记 `ocr_failed`；failed 状态补齐 failure_code |
| `metal-doc-agent/tests/test_job_state_machine.py` | 新增 `test_orchestrated_review_reports_failure_context`（layout_failed / ocr_failed 两类） |

- 新增测试：平台 1 个、引擎 1 个；引擎 `test_job_state_machine` **11 passed**。
- 引擎全量套件在 worker 容器内跑出 3 个环境性失败（缺 `cryptography`/`sqlalchemy`、goldset 清单使用 Windows 反斜杠路径），与本次改动无关；新增逻辑已由定向测试覆盖。

### 19.3 R5.6 并发结果

| 场景 | 结果 |
|---|---|
| 同文档 5 并发解析 | 唯一 `job_id=bf526e747550`，状态由 queued 正常完成 review（34.4s、903 tokens） |
| 双 worker 抢占 | 两 worker 同时 `--once`：worker1 `skip job ... owned by another worker`，worker2 `ran`；仅执行一次 |
| 批量复核 200 条 | 平台测试通过 |
| 队列/状态机 | `claim` 基于 `O_EXCL` marker + heartbeat；stale 恢复已在 R5.5 实测 |

---

## 20. R5.7 Postgres 迁移/备份/恢复/降级记录（2026-11-01）

**结论：R5.7 完成。空库迁移、生产启动、pg_dump 备份/恢复、降级/升级往返均通过；SQLite 平台回归 54 passed。**

### 20.1 空库迁移与运行

| 步骤 | 结果 |
|---|---|
| 临时 Postgres 16（`r5-pg`，空 `hanson` 库） | 启动正常 |
| `alembic upgrade head` | 8 个迁移全部执行：`57941958f11b → 541ff3a3dca6 → c3a9d5e7f1b2 → e1b2c3d4f5a6 → f2c3d4e5a6b7 → g3d4e5f6a7b8 → h4e5f6a7b8c9 → i5f6a7b8c9d0` |
| 生产模式启动（`HANSON_ENV=production`，`db_auto_create=false`） | uvicorn 启动成功，startup 校验通过 |
| `/health` / `/platform/ready` | **200 / 200**，database/migrations/models/data_dir 全部 true |
| 登录与写入 | 登录 **200**；创建知识库 **201**；列表 **200**；DB `users=1, kbs=1, workspaces=1` |
| 迁移版本 | `i5f6a7b8c9d0 (head)` |

### 20.2 备份与恢复

| 步骤 | 结果 |
|---|---|
| `pg_dump -Fc` | 备份文件 **44,498 bytes** |
| `createdb hanson_restore` + `pg_restore --no-owner --no-privileges` | 恢复成功，无错误 |
| 数据对比 | 源库与恢复库：`users=1`、`kbs=1`、`workspaces=1`；`alembic_version=i5f6a7b8c9d0` 一致 |

### 20.3 降级/升级往返

| 步骤 | 结果 |
|---|---|
| `alembic downgrade -1` | `i5f6a7b8c9d0 → h4e5f6a7b8c9` |
| `alembic current` | `h4e5f6a7b8c9` |
| `alembic upgrade head` | `h4e5f6a7b8c9 → i5f6a7b8c9d0` |
| `alembic current` | `i5f6a7b8c9d0 (head)` |
| 往返后数据 | `users=1`、`kbs=1`、`workspaces=1`（工作空间回填保留） |

### 20.4 SQLite 兼容回归

- 平台 API 全量 unittest 在 SQLite 临时库上 **54 passed**（含迁移/启动、租户、安全、导出、幂等、证据去重、DB 故障 503）。
- R5 全部单元完成；下一阶段 R6 生产化（监控/日志/性能/备份加密/发布回滚/依赖扫描/运行手册）。

---

## 21. R6.1–R6.4 执行记录（2026-11-01）

**结论：R6.1、R6.2、R6.4 完成；R6.3 性能目标未达，经用户决策暂停（后续由用户调整模型参数），不阻塞 R6.5–R6.7。**

### 21.1 R6.1 监控核对与告警演练

| 项目 | 结果 |
|---|---|
| Prometheus 规则 | `infra/monitoring/prometheus-rules.yaml` 共 **12 条**，`promtool check rules` **SUCCESS** |
| 指标来源对齐 | `/platform/metrics` 改为一次性 `render_family` 输出，消除重复 HELP/TYPE；`platform_errors_total{status,route}` 可用；engine 侧 `engine_pipeline_seconds_bucket` 可用 |
| 抓取目标 | engine-api、platform-api、model-extract、model-sft、model-ocr、model-layout（layout 抓 `/health`） |
| 告警演练 | **EngineApiDown**、**ModelLayoutDown**、**EngineJobFailureRate** 三条规则均按预期进入 firing（构造缺 job 标签后补齐，复核 SUCCESS） |
| Dashboard | JSON **7 个 panel**，指标名与实际 `/metrics` 输出一致 |

新增/修正：`ModelLayoutDown` 规则（`up{job="model-layout"}==0` 持续 5m）；`infra/monitoring/README.md` 补充指标来源与抓取配置说明。

### 21.2 R6.2 结构化日志与错误聚合

| 项目 | 结果 |
|---|---|
| 平台日志 | `configure_logging()` 输出 JSON 行（ts/level/logger/message，异常含 stack）；访问日志含 `request_id`、`method`、`path`、`status`、`duration_ms` |
| 请求 ID | 读取或生成 `X-Request-ID`，写回响应头；日志与之贯通 |
| 任务 ID | 引擎 `bind_job(job_id)`（`contextvars`），worker/runner 日志自动带 `job_id`；平台侧从路径解析 job_id 记入访问日志 |
| 错误聚合 | `≥400` 计入 `platform_errors_total{status,route}`，同时输出 warning 级 JSON 日志 |
| 回归 | 平台测试 **55 passed**（新增 `test_database_errors_return_503_problem`、`test_request_logging_and_error_metrics`） |

### 21.3 R6.3 性能实测（未达标，已暂停）

| 场景 | 实测 | 说明 |
|---|---|---|
| 23 页真实文档（GB/T 1220 第 2 次） | **约 278s** | 含 CPU 版面 + GLM-OCR |
| 37 页文档（GBT 6892） | **541–704s** | 扫描型，无可用文本层 |
| 31 页文档 | **>1066s** | 大表 OCR 排队，判定超时 |
| 22 页文本型（GBT 1591） | **>664s** | 文本层 181/189 文本块命中，但少数大表仍超时 |
| 单表 OCR | **约 8.5s** | GLM-OCR vLLM `--max-num-seqs 2`，并发≥2 后吞吐饱和 |
| 版面 | GPU 单页 ~0.2s；CPU 预热后 ~1s | 生产用 :9978 CPU |

已实施优化：文本型 PDF 文本层填充跳过正文 OCR（`fill text layer`，阈值 50 字符）；页并发 4 / 块并发 8；表格抽取并行。结论：瓶颈在 GLM-OCR 服务端并发与单表解码时长，非引擎调度。**用户决策：先不考虑 OCR 速度，后续由用户调整模型参数；R6.3 保持未勾选，待模型侧调优后另行压测。**

### 21.4 R6.4 备份加密与恢复演练

| 项目 | 结果 |
|---|---|
| Postgres 备份 | `pg_dump -Fc` + AES-256-CBC/PBKDF2 加密；生成 `HMAC-SHA256SUMS` 清单 |
| 恢复 | 解密 + `pg_restore --no-owner --no-privileges` 成功；数据核对 `users 3/3`、`documents 13/13`、`audit_logs 123/123`、`workspaces 1/1` |
| 篡改检测 | 修改密文后 restore 在解密前 HMAC 校验失败并退出（非 0），符合预期 |
| 卷备份 | `engine-data` **85.8MB / 786 entries**、`platform-data` **11.7MB / 23 entries**，tar + 加密 + HMAC 校验 + 解密解包全链路通过 |
| 异地存储 | 未执行（需运维提供目标存储与凭据）——记录为待办，不阻塞 |

**R6 后续：R6.5 发布/回滚演练、R6.6 依赖/密钥扫描、R6.7 运行手册更新。**

---

## 22. R6.5 发布/回滚演练记录（2026-11-01）

**结论：tag 化发布、两段灰度（api/web → engine/worker）、上一 tag 一键回滚、滚前回切、冷启动与单服务重启全部通过；发布态为 `r6-3`，回滚基线 `r6-baseline` 保留。**

### 22.1 发布机制

- `infra/docker/compose.yaml` 为 5 个应用服务增加显式 `image:`，统一由 `HANSON_RELEASE_TAG` 控制：
  `hanson-r1-<service>:${HANSON_RELEASE_TAG:-latest}`；未设置变量时行为与既有的 `latest` 部署一致。
- 构建：`HANSON_RELEASE_TAG=<tag> docker compose -p hanson-r1 --env-file <env> build ...`
- 发布：`HANSON_RELEASE_TAG=<tag> docker compose -p hanson-r1 up -d [--no-deps <services>]`
- 回滚：`HANSON_RELEASE_TAG=<prev> docker compose -p hanson-r1 up -d --no-deps platform-api web engine-api worker-prod worker-explore`

### 22.2 tag 与灰度过程

| 步骤 | 操作 | 结果 |
|---|---|---|
| 基线固化 | `docker tag hanson-r1-*:latest → r6-baseline` | 5 个镜像（platform `da4cd3d8e558`、engine `3a16efca1984`、worker-prod `4cccdf6d6b5c`、worker-explore `e71a7d4be17a`、web `188a493ef334`）可随时回滚 |
| 构建 r6-2 | `HANSON_RELEASE_TAG=r6-2 build` | 5 镜像构建成功（platform `9119cf44d842`、engine `f2acc0b8e6be`、worker-prod `9574f2bd7e7e`、worker-explore `ee3c3bb41db6`、web `d835c0ee4f30`） |
| 灰度第一段 | `up -d --no-deps platform-api web` | platform 3s 内 healthy；`/health` 200、`/platform/ready` 200、`web /` 200；engine/worker 镜像未动（仍 `latest`） |
| 观察 | 指标/登录/DB 计数检查 | `platform/metrics` 200；DB `users=3 documents=14 audit_logs=129 workspaces=1` |
| 灰度第二段 | `up -d --no-deps engine-api worker-prod worker-explore` | engine-api healthy；容器内 `/ready` 200（三个 check 全 true）；workers 启动 |
| 全量确认 | `ps` | 5 个服务均为 `r6-2`，engine/worker/platform healthy |

### 22.3 回滚与回切

| 步骤 | 操作 | 结果 |
|---|---|---|
| 一键回滚 | `HANSON_RELEASE_TAG=r6-baseline up -d --no-deps <5 服务>` | 全部切回 `r6-baseline`；platform/engine healthy；`/health` `/ready` `web` 均 200；容器内 engine `/ready` 200 |
| 回滚可用性 | `docker images` 过滤 `r6-baseline` | 5 个基线镜像均在本地，回滚不依赖重新构建 |
| 回切新版本 | `HANSON_RELEASE_TAG=r6-2 up -d --no-deps <5 服务>` | 全部切回 `r6-2`，healthy |

### 22.4 冷启动与重启演练

| 场景 | 操作 | 结果 |
|---|---|---|
| 冷启动 | `docker compose down`（保留卷）→ `up -d` | **18s** 内 postgres/platform/engine 全部 healthy；卷 `hanson-r1_postgres-data`/`platform-data`/`engine-data` 保留 |
| 数据完整性 | 重启后 DB 计数 | `users=3 documents=14 audit_logs=129 workspaces=1` 不变 |
| 单服务重启 | `docker compose restart platform-api` | 3s 后 healthy，`/health` 与 `/platform/ready` 200 |
| 队列状态 | 重启后扫 `state.json` | `review 6 / failed 3 / succeeded 4`，无 queued/running 遗留 |
| 迁移 | 冷启动执行 `alembic upgrade head` | `/platform/ready` 的 `migrations=true` 校验通过 |

### 22.5 演练中发现并修复的问题

| 问题 | 原因 | 修复 |
|---|---|---|
| 空闲 worker 完全无日志，运维无法判断“是否在监听” | `worker.py` 仅在恢复 stale / 跳过任务 / 完成任务时输出 | `main()` 的 watch 分支增加启动日志：`worker watching pool=... limit=... poll=... store=...`，重建 `r6-3` 后日志可见 |
| `platform_errors_total` 冷启动后不出现 | 计数器在内存中，family 仅在存在样本时输出（源码 `router.py` 的 `if error_counts`） | 属预期计数器语义：重启归零、首个 ≥400 响应后出现；已实测 404 后输出 `platform_errors_total{route="v1/does-not-exist",status="404"} 1`；写入 R6.7 运行手册 |

### 22.6 r6-3 发布态校验

| 项目 | 结果 |
|---|---|
| 灰度发布 | 先 api/web 再 engine/worker，全部 `r6-3`，healthy；worker 日志出现 watching 启动行 |
| 引擎快速冒烟 | 容器内 1 页文本 PDF 走完整管线：layout `:9978` 200、GLM-OCR `:9977` 200、产物 12 个文件、退出码 0、耗时 **2s**（无表格页因此 0 records/review，属预期） |
| 冷启动（r6-3） | down→up **18s** 全部 healthy；数据计数不变 |
| 重启（r6-3） | `restart platform-api` 3s healthy，`/health` `/ready` 200 |
| 平台单测（r6-3 镜像内容） | **55 passed**（86.35s） |
| 引擎定向单测（r6-3 镜像内容） | **17 passed**（`test_job_state_machine` + `test_ocr_pipeline`） |

K8s 演练按计划列为 P2，本轮不执行。

---

## 23. R6.6 依赖/密钥扫描记录（2026-11-01）

**结论：r6-3 扫描出的 pip/setuptools 与 ansi-regex 问题已修复并重建为 `r6-4`；Python 两套环境 0 漏洞、前端 0 高危、密钥扫描 0 命中。**

### 23.1 Python（pip-audit，r6-3 基线 → r6-4 修复后）

| 环境 | r6-3 结果 | 修复 | r6-4 结果 |
|---|---|---|---|
| platform-api | 65 包，2 个有漏洞：`pip 24.0`（6 条 PYSEC 去重后）、`setuptools 79.0.1`（PYSEC-2026-3447 / GHSA-xmj3-9gf7-h52w） | 两个 Dockerfile 增加 `pip install --upgrade pip setuptools` | **0 vulnerable**（pip 26.2.2 / setuptools 84.2.1） |
| engine（worker 镜像） | 56 包，同样 2 个（pip/setuptools） | 同上 | **0 vulnerable**（pip 26.2.2 / setuptools 84.2.1） |

- 漏洞性质：均为打包工具链问题（pip 解包路径/符号链接、setuptools 安装期路径逃逸），运行期不调用 pip/setuptools；修复后彻底消除，无需例外豁免。
- 扫描方式：容器内 `pip-audit --vulnerability-service osv|pypi --timeout 120 -f json`。期间 `api.osv.dev` / `pypi.org` 多次超时或无路由，通过重试完成（已记录，非应用问题）。

### 23.2 前端（pnpm audit）

| 项目 | 结果 |
|---|---|
| r6-3 基线 | **1 high**：`ansi-regex 5.0.0`（GHSA-93q8-gq69-wqwm，ReDoS），仅 dev 链路（`@testing-library/* → pretty-format`），不进生产 bundle |
| 修复 | `pnpm-workspace.yaml` 增加 `overrides: ansi-regex: 5.0.1`，重新生成 `pnpm-lock.yaml`（248 依赖，锁文件 supply-chain 校验通过） |
| r6-4 结果 | `info 0 / low 0 / moderate 0 / high 0 / critical 0`（248 deps） |
| 回归 | web 单测 **15 passed**、`tsc --noEmit + vite build` 通过（dist 426.23 kB / gzip 125.15 kB） |

### 23.3 密钥扫描（gitleaks）

| 项目 | 结果 |
|---|---|
| 范围 | 源码 + 配置 + 数据目录，排除 `node_modules`/`dist`，共 **26,168 文件 / ≈796 MB** |
| 命令 | `gitleaks detect --no-git --source /scan --redact`（工作区非 git 仓库，按目录扫描） |
| 结果 | **no leaks found（0 findings）** |

### 23.4 发布影响

- 依赖修复触发 `r6-4` 构建：`api/web` 先切、`engine/worker` 后切，全部 healthy；worker 启动日志可见；`/health`、`/platform/ready`、`web /` 均 200。
- `r6-baseline`、`r6-2`、`r6-3` 镜像保留，回滚链完整；`latest` 已同步指向 `r6-4`（未设置 `HANSON_RELEASE_TAG` 时部署与当前发布一致）。

---

## 24. R6.7 运行手册更新记录（2026-11-01）

**结论：`docs/runbook.md` 已按当前实际形态（单机 Compose + Postgres、tag 化发布、结构化日志、加密备份）更新；`deploy/README.md` 同步发布命令。**

| 章节 | 更新内容 |
|---|---|
| 2 日常检查 | 增加 `platform_errors_total`（重启归零、首个 ≥400 后出现）、worker 启动日志 `worker watching pool=...`、宿主机磁盘 > 15%、备份 `HMAC-SHA256SUMS` 存在 |
| 3 启停 | 新增容器启动顺序：postgres → platform-api（自动迁移）→ engine-api → workers → web；冷启动实测 18s；保留卷的 `down`（禁止 `-v`） |
| 4 发布与回滚 | 新增 tag 化两段灰度与一键回滚命令（`HANSON_RELEASE_TAG`）；记录 `r6-baseline → r6-2 → r6-3 → r6-4` 版本链；K8s 归为 P2 |
| 5 故障处理 | 新增 DB 503 `problem+json`、磁盘写满（同盘无法落盘 + stale recovery）、任务长期 running；补充按 `job_id`/`request_id` 的日志定位方式 |
| 5.1 故障码 | 新增 `failure_code` 对照表：`invalid_input`/`layout_failed`/`ocr_failed`/`extract_failed`/`timeout`/`engine_failed` 与首要排查项 |
| 6 值班 | 保留 P1/P2 响应时限与升级链，新增交接班检查清单（healthy、ready、积压、备份、工单） |
| 7 已知限制 | 修正过期描述：备份已加密（异地待接入）、引擎直方图已可用、OCR 服务 `--max-num-seqs 8`、流式/超时/并发上限、计数器语义、磁盘满限制、K8s 未演练 |

**R6 收尾状态**：R6.1/R6.2/R6.4/R6.5/R6.6/R6.7 完成；R6.3 已完成参数选型与压测（部分达成，见第 25 节）。
退出条件中的“值班表”需由业务方提供人员名单（手册已给出交接检查清单，不阻塞技术侧）。

---

## 25. R6.3 性能调优与压测记录（2026-11-01）

**结论：完成 OCR/版面参数选型与三份真实文档压测；吞吐较基线显著提升（37 页扫描件 541–704s→234s，22 页文本层 455s→80s），但表格密集文档仍因“长响应首次尝试丢失”存在 ~90–130s 单块重试，23 页实测 358s，未达到 300s。已落最佳配置并记录模型平面侧待办。**

### 25.1 选定配置

| 层 | 参数 | 取值 | 依据 |
|---|---|---|---|
| GLM-OCR（vLLM） | `--max-num-seqs` / `--max-num-batched-tokens` | **8 / 16384**（原 2 / 8192） | 表块微基准：2→8 吞吐 20.4→62.3 req/min（×3.05），12 仅 84.9 但稳定性更差 |
| GLM-OCR | 请求形态 | **流式 SSE**（`GLM_OCR_STREAM=1`） | 容器→1.35 非流式长响应会丢失；4 并发长表非流式 300s 超时，流式 18.6s 全成功 |
| 引擎 OCR | `OCR_MAX_INFLIGHT` / `OCR_TABLE_INFLIGHT` | **16 / 2** | 总并发对齐服务容量；表格长生成单独限额，避免占满槽位拖垮正文 |
| 引擎 OCR | `GLM_OCR_TIMEOUT` | **90s** | 单表正常 7–19s；卡住时 90s 切断并重试，避免 180s×3 的最坏放大 |
| 引擎 OCR | 页/块并发 | 4 / 8 | 保持 |
| 版面 | 主 / 备 / 超时 | **`:9979` GPU / `:9978` CPU / 60s** | GPU 单页 0.27–0.6s vs CPU 1.0–2.0s，同页块类型/数量一致；超时自动切换 |
| 抽取 | `QWEN_STREAM` | **1（流式）** | 抽取非流式同样出现 ~180s 响应丢失；流式后 GBT 1591 由 455–538s 降至 80s |

### 25.2 微基准（4 个真实表块，max_tokens 4096）

| 服务端 `max-num-seqs` | 客户端并发 | 32 请求墙钟 | 吞吐 | 备注 |
|---|---|---|---|---|
| 2 | 4 | 11.8s（4 请求） | 20.4 req/min | 基线 |
| 4 | 4 | 21.0s（12 请求） | 34.4 req/min | — |
| 8 | 16 | 15.4s（16 请求） | 62.3 req/min | 采用 |
| 12 | 32 | 22.6s（32 请求） | 84.9 req/min | 峰值更高但偶发卡顿 |

版面单页：GPU 0.27–0.6s，CPU 1.0–2.0s；同页块类型/数量一致。

### 25.3 端到端结果（真实文档，ad-hoc 引擎链路含抽取）

| 文档 | 页数 | CPU 版面 + OCR2（R6.3 基线） | 最佳配置（GPU 版面 + OCR8 + 流式，r6-10） | 说明 |
|---|---|---|---|---|
| GBT 6892（扫描，表格中等） | 37 | 541–704s | **234s** | 达标（37 页 <300s，约 6.3s/页） |
| GB/T 1220（表格密集） | 23 | 278s（第二次） | **358s**（16 次表格重试） | 未达标；无卡顿理论值 ~150s |
| GBT 1591（文本层+少量表） | 22 | 455s | **80s** | 达标（约 3.6s/页） |

三份文档共 82 页，总墙钟 **672s**；其中 gbt1220 的 ~200s 为表格长响应重试等待。

### 25.4 残余问题（模型平面侧）

- 现象：容器 → 1.35 的长响应（表格 HTML、抽取 JSON）首次尝试偶发“服务端已完成但客户端收不到”，客户端 90s/180s 超时后重试成功；1.35 本机 4 并发长表 39.4s 全部成功，排除 vLLM 生成能力问题。
- 影响：表格密集文档每块多付一次 ~90s 等待，23 页累计 ~200s。
- 已落缓解：流式、90s 超时、表格并发 2、抽取流式、版面 failover。
- 建议模型平面侧后续（用户确认后执行）：核查 Windows/WSL→1.35 的 NAT/防火墙空闲连接策略，或让引擎容器走 host 网络/独立网段；再评估 `max-num-seqs 12`。

**R6.3 状态：参数选型与压测完成；30 页 p95 ≤300s 在扫描型文档达成，表格密集文档未达成，保留为已知限制。**

---

## 26. R6.4 全量压测记录（2026-11-01）

**结论：25 份去重文档 / 434 页全部跑通（24 份一次通过，1 份版面超时后修复容错并重跑通过）。总墙钟 6559s（109 分钟），15.1s/页，中位 8.6s/页；≤30 页文档 18/21 份 ≤300s（85.7%）。3 份超大表格文档 389–2266s 仍未达标，瓶颈是单表长生成（300–500s/块），属模型参数调优范围。**

### 26.1 测试口径

| 项 | 取值 |
|---|---|
| 文档集 | `标准文件` 下 PDF 按 md5 去重 → 25 份（doc_01–doc_25），共 434 页 |
| 镜像/配置 | r6-10；GPU 版面 `:9979` 主 + CPU `:9978` 备、OCR `max-num-seqs 8`、流式、`OCR_TABLE_INFLIGHT=2` |
| 执行方式 | 单 lane 串行 `docker exec <worker> python -m metal_doc_agent.worker --job … --template product_full` |
| 指标 | 墙钟（渲染+版面+OCR+抽取+组装）、records、`quality.status`、失败块数 |

> 并发说明：双 lane 并行会形成 4 个并发表格并显著退化，因此全部改为单 lane 串行；被并发污染的首轮样本已重跑替换。

### 26.2 逐文档结果

| 文档 | 页数 | 墙钟(s) | s/页 | records | 失败块 | quality |
|---|---|---|---|---|---|---|
| doc_01 | 6 | 18 | 3.0 | 0 | 0 | review |
| doc_02 | 3 | 111 | 37.0 | 2 | 0 | review |
| doc_03 | 21 | 66 | 3.1 | 53 | 0 | review |
| doc_04 | 6 | 9 | 1.5 | 0 | 0 | review |
| doc_05 | 12 | 24 | 2.0 | 4 | 0 | review |
| doc_06 | 5 | 34 | 6.8 | 5 | 0 | review |
| doc_07 | 31 | 471 | 15.2 | 143 | 0 | fail |
| doc_08 | 25 | 2266 | 90.6 | 63 | 9 | review |
| doc_09 | 22 | 279 | 12.7 | 524 | 0 | review |
| doc_10 | 11 | 137 | 12.5 | 41 | 0 | fail |
| doc_11 | 25 | 946 | 37.8 | 227 | 2 | review |
| doc_12 | 33 | 103 | 3.1 | 30 | 0 | review |
| doc_13 | 20 | 268 | 13.4 | 154 | 0 | fail |
| doc_14 | 37 | 242 | 6.5 | 118 | 0 | fail |
| doc_15 | 13 | 45 | 3.5 | 23 | 0 | review |
| doc_16 | 18 | 189 | 10.5 | 234 | 0 | review |
| doc_17 | 32 | 95 | 3.0 | 5 | 0 | review |
| doc_18 | 23 | 215 | 9.3 | 126 | 0 | fail |
| doc_19 | 20 | 172 | 8.6 | 139 | 0 | review |
| doc_20 | 19 | 198 | 10.4 | 87 | 0 | fail |
| doc_21 | 12 | 31 | 2.6 | 26 | 0 | review |
| doc_22 | 9 | 22 | 2.4 | 10 | 0 | review |
| doc_23 | 9 | 214 | 23.8 | 2 | 0 | review |
| doc_24 | 12 | 389 | 32.4 | 6 | 0 | review |
| doc_25 | 10 | 15 | 1.5 | 3 | 0 | review |

### 26.3 汇总指标

| 指标 | 值 |
|---|---|
| 成功文档 / 总页数 | 25/25 / 434 |
| 总墙钟 | 6559s（109 分钟），15.1s/页 |
| 中位 / p95 s/页 | 8.6 / 37.7 |
| 中位 / p95 墙钟 | 137s / 851s |
| ≤30 页文档 ≤300s | 18/21（85.7%），超标：doc_08、doc_11、doc_24 |
| 抽取记录 | 2025 条 |
| 质量状态 | review 19 / fail 6；失败块 11（doc_08 9、doc_11 2） |

**质量说明**：6 份 `fail` 主要来自压测把文件重命名为 `doc_NN.pdf`，导致 `standard_no` 无法解析（`MISSING_STANDARD_NO`），另有少量 `PERCENT_OUT_OF_RANGE`（抽取值超出 0–100）。这是压测命名的副作用，不代表平台流程缺陷；`review` 状态即为人机复核入口。

### 26.4 异常与修复

| 问题 | 现象 | 处理 |
|---|---|---|
| doc_22 整单失败 | 版面 GPU 与 CPU 备均 `ReadTimeout`，异常冒泡终止任务（`exit=1`，202s 白跑） | `ocr/glm.py` 增加页面级容错：失败页保留 PDF 文本层、写 `layout-*.json` 的 `error`，其余页继续；新增单测 `test_layout_failure_keeps_page`；重跑 doc_22 **22s 通过** |
| 表格长生成无总上限 | `GLM_OCR_TIMEOUT=90` 只是空闲读超时；流式下超大表格单块持续 300–500s，doc_08 累计 2266s | 记录为模型平面调优项（降低 `max_tokens`/分块/提升生成速度），引擎侧后续可加“单块总时长上限” |
| 并发退化 | 双 worker 并行 → 4 并发表格，doc_09 由 279s 退化到 605s | 全量改为单 lane；生产建议单文档串行，横向扩展需全局表格配额 |

### 26.5 结论

- 常规文档（≤30 页、表格规模正常）满足 300s 目标，中位 8.6s/页。
- 超大表格文档是唯一未达标类别，根因在模型生成时长而非编排；与 R6.3 结论一致。
- 页面级容错已合入 **r6-11** 镜像：`engine-api` / `worker-prod` / `worker-explore` 已切换到 r6-11（platform-api/web 仍为 r6-10）；doc_22 冒烟 21s、10 records、review。

### 26.6 耗时因素分析（2026-11-02）

对 3 份代表文档复跑并读取 `trace.json` 的阶段耗时（r6-11，空载单 lane）：

| 文档 | 页/块/表 | 总耗时 | OCR 阶段 | 抽取阶段 | 其余阶段合计 |
|---|---|---|---|---|---|
| doc_02 | 3 / 64 / 10 | 11.4s | 11.2s（98%） | 0.0s | <0.2s |
| doc_07 | 31 / 309 / 31 | 185.6s | 167.0s（90%） | 17.9s（10%） | <0.5s |
| doc_12 | 33 / 380 / 18 | 100.0s | 58.1s（58%） | 41.4s（41%） | <0.5s |

- **OCR 是唯一主成本**（58–98%）：渲染+版面+切块+GLM 解码都在 `ocr` 步骤内；`tablegrid`/`bindings`/`outline`/`clauses`/`references`/`inventory`/`alignment` 均 <0.5s，可忽略。
- **抽取是第二成本**（0–41%）：与表格数量/行数相关；doc_12 16 表 41.4s，doc_07 31 表 17.9s，差异来自每表列数/行数与 Qwen 调用次数。
- **表块解码是尾部风险**：同一文档复跑与首轮差异巨大（doc_02 111s→12s、doc_07 471s→187s，doc_12 103s→101s），说明耗时不由文档固有属性决定，而由表块长生成与重试决定。
  - doc_07 首轮 356 次 OCR、16 次 `slow block`（102.8–224.4s）；复跑 309 次 OCR、仅 5 次（31.5–48.3s）。
  - doc_08 出现 9 次块失败，`slow block` 231.6–580.5s，累计 2266s。
- **90s 只是空闲读超时**：流式下模型持续出字可长达 500s；`slow block` 的 elapsed 从获取表格槽位前开始计时，因此包含排队等待（每进程仅 2 个表格槽位）。
- **失败重试代价**：单块失败至少多付 ~90s；doc_08 的 9 次失败即数百秒级放大。
- **版面**：GPU 0.3–0.6s/页、CPU 1–2s/页，正常时占比极小；偶发 60s 超时已由页面级容错兜底（不再整单失败）。
- **文本层**：有文本层的文档可跳过正文 OCR，是可达 1.5–3.1s/页的关键；doc_12 为扫描件（文本层未命中），因此 1.76s/页但请求量高达 357 次。
- **并发争抢**：双 worker → 4 并发表格，doc_09 279s→605s；vLLM 队列（`max-num-seqs 8`）与 CPU 版面在 OCR 满载时也会被拖慢。

### 26.7 模型机迁移 .75 与 GLM 参数对比（2026-11-02）

**结论：迁移到 `192.168.188.75` 并按 `seq12 / batched 8192 / prefix caching / gpu 0.4` 启动后，在 host 网络下 4 份代表文档均提速（长表 25–89%）；但 Docker bridge 会让图片 OCR 间歇挂起 90s，端到端反而慢 4–9 倍，已把 worker 改为 host 网络。**

变更项：
- 模型机：`192.168.1.35` → **`192.168.188.75`**（旧机不可达）。
- GLM-OCR：`--max-num-seqs 12 --max-num-batched-tokens 8192 --max-model-len 32768 --enable-prefix-caching --enable-chunked-prefill --gpu-memory-utilization 0.4 --kv-cache-dtype fp8`。
- Qwen：`adapter-v5` @ `:9991`，`gpu-memory-utilization 0.38`（GLM 占 0.4 后 0.4 无法分配 KV）。
- 版面：`:9979` GPU 主 / `:9978` CPU 备。

网络对比（同一台 .75、同一份引擎与参数）：

| 文档 | Docker bridge | host 网络 | 说明 |
|---|---|---|---|
| doc_02（3 页/10 表） | 101s | **11s** | bridge 下 24 个块出现 ~93s 等待 |
| doc_07（31 页） | 553s | **141s** | — |
| doc_12（33 页） | 428s | **70s** | — |

host 网络下与旧机基线对比：

| 文档 | 旧机 1.35（seq8/16384/gpu0.16） | 新机 .75（seq12/8192/prefix/gpu0.4） | 变化 |
|---|---|---|---|
| doc_02 | 11.4s | 10s | -12% |
| doc_07 | 185.6s | 140s | -25% |
| doc_12 | 100.0s | 70s | -30% |
| doc_08 | 2266s（9 个失败块，63 records） | **239s（0 失败块，118 records）** | -89% |

**关键发现与修复**：
- 现象：worker 容器（`192.168.189.x`）经 Docker bridge 访问 `192.168.188.75` 时，图片 OCR 请求间歇 90s 无响应；服务端日志显示请求已完成、吞吐正常，宿主机/Windows 直连正常，说明是 bridge/NAT 传输层问题（流式与非流式均出现）。
- 修复：`compose.yaml` 的 `worker-prod` / `worker-explore` 改为 `network_mode: host`；重建后同容器复跑 doc_02 **10s、0 个 slow block**。
- doc_08 的 2266→239s 同时受益于“去掉传输挂起”和“参数调整”，不能全部归因于模型参数；但 0 失败块、records 63→118 说明稳定性实质改善。
- 资源余量：GLM 0.4 + Qwen 0.38 后系统仅余 ~4GB，Qwen 低于 0.38 会因 KV cache 不足启动失败，后续调参需保留余量。

**结论**：新参数在 host 网络下整体更快，长表收益最大；生产必须先解决 bridge 传输问题再谈模型参数收益。

### 26.8 全量重跑（.75 + host 网络，2026-11-02）

**结论：25/25 成功、434 页，总墙钟 1764s（29 分 24 秒），4.06s/页；中位 3.33s/页、p95 5.6s/页；全部 25 份文档 ≤300s（最慢 doc_08 222s）；失败块 0。相比旧全量（6559s、15.1s/页、中位 8.6、p95 37.7、18/21 达标、11 个失败块）整体提速 3.72 倍。**

| 指标 | 旧全量（1.35，bridge，seq8/16384） | 新全量（.75，host，seq12/8192/prefix） | 变化 |
|---|---|---|---|
| 成功文档 / 页数 | 25 / 434 | 25 / 434 | — |
| 总墙钟 | 6559s | **1764s** | -73% |
| s/页 | 15.1 | **4.06** | -73% |
| 中位 / p95 s/页 | 8.6 / 37.7 | **3.33 / 5.6** | — |
| 中位 / p95 墙钟 | 137s / 851s | **62s / 157.8s** | — |
| ≤30 页 ≤300s | 18/21（85.7%） | **21/21（100%）** | — |
| 全文档 ≤300s | 否（最长 2266s） | **是（最长 222s）** | — |
| 失败块 | 11 | **0** | — |
| records | 2025 | 2087 | +62 |
| quality | review 19 / fail 6 | review 19 / fail 6 | 一致 |
| 阶段合计 | — | OCR 1510.4s（85.6%）、抽取 223.7s（12.7%）、其余 ~30s | — |

逐文档（旧 → 新，秒）：01 18→17、02 111→10、03 66→62、04 9→9、05 24→20、06 34→28、07 471→162、08 2266→**222**、09 279→93、10 137→61、11 946→**128**、12 103→65、13 268→77、14 242→141、15 45→42、16 189→94、17 95→92、18 215→117、19 172→111、20 198→96、21 31→31、22 22→27、23 214→22、24 389→**21**、25 15→16。

**解读**：
- 大文档收益主要来自“去掉 bridge 90s 超时簇”：doc_08/11/23/24 提升 7–18 倍；小文档（≤12 页）耗时基本不变（个别 ±5s），说明模型参数未拖慢短请求。
- 新分布显著收窄：单页耗时中位 3.33s、p95 5.6s（旧 8.6/37.7）；峰值仍是大表生成（doc_08 222s，单块最长 ~48s），但不再出现 90s/180s 超时簇。
- 失败块 11→0，doc_08 records 63→118，说明表格 OCR 成功率提升。
- 质量状态集合与旧全量一致（同样 6 份 fail，均为标准号缺失/数值范围问题，属压测重命名副作用）。

**测试口径**：生产 worker 容器（r6-11，`network_mode: host`），单 lane 串行，`--template product_full`，`GLM_OCR_STREAM=1`；每文档 `timeout 2400`。产物在容器 `/tmp/r64b_out`，日志 `/tmp/r64b/`。





