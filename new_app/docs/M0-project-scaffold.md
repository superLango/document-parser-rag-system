# M0 里程碑详细执行计划：项目启动与脚手架

> 文档版本：v1.5  
> 编制日期：2026-11-11  
> 计划周期：2026-11-11 ~ 2026-11-18  
> 主责角色：项目负责人（兼架构/DevOps）  
> 协作角色：外部模型服务器管理员（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 当前状态：进行中（脚手架已落地，待验收）

---

## 1. 里程碑目标

建立 `new_app/` 的工程骨架，使后续所有服务、前端、测试、部署工作有统一落点；本阶段不实现任何业务逻辑，只完成：

- 目录结构、Python/前端工程、依赖管理。
- 服务骨架与健康检查。
- 契约包与 schema 基线。
- 本地开发环境（Docker Compose）。
- CI 门禁（lint/typecheck/单测/契约/import 检查）。
- 旧代码提取的 provenance 规范。
- 关键 ADR 与文档索引。

## 2. 范围与不做

### 2.1 本阶段范围

| 项 | 内容 |
|---|---|
| 目录 | `new_app/` 全部目录骨架 |
| Python | uv/pyproject workspace、共享包、七个服务骨架 |
| 前端 | `new_app/web` Vite + React + TS 骨架 |
| 契约 | `packages/contracts` OpenAPI/JSON Schema 占位 |
| 基础设施 | Compose：Postgres、MinIO、Redis、服务占位 |
| WSL K8s | 本地 WSL 安装轻量 K8s（k3s/kind/minikube PoC 后固定一种） |
| API 前缀 | 公开 API 统一 `/v1`，内部 `/internal` |
| CI | lint、typecheck、单测、契约校验、import-linter |
| 规范 | PROVENANCE、ADR、README、配置样例 |
| 文档 | 文档索引、开发环境说明、Q1–Q8 归档链接 |

### 2.2 本阶段不做

- 不实现上传、解析、OCR、配方、沙箱、Agent、审核、反馈业务逻辑。
- 不连接真实模型、真实 OCR、真实沙箱。
- 不迁移旧数据。
- 不实现前端页面（只搭骨架）。
- 不修改旧 `apps/`、`metal-doc-agent/`。

## 3. 前置依赖

| 依赖 | 状态 | 说明 |
|---|---|---|
| 架构方案确认 | 必须 | [架构重构方案](architecture-refactor-plan.md) |
| 整体开发计划确认 | 必须 | [整体开发计划](development-plan.md) |
| 开发机环境 | 必须 | Python 3.11+、Node 20+、Docker/Compose、WSL |
| WSL 资源 | 必须 | 可安装轻量 K8s + MinIO；资源不足时用远程 Linux |
| 代码仓库分支 | 必须 | 建议新建 `refactor/new-app` 分支 |
| 对象存储 | 已确认 Q6 | 本地开发/测试统一 MinIO |
| 人力 | 已确认 Q8 | 当前 1 人，串行执行 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D0.1 | `new_app` 目录骨架 | `new_app/` | 目录 | 架构负责人 |
| D0.2 | Python workspace | `new_app/pyproject.toml`、`uv.lock` | 配置 | 架构负责人 |
| D0.3 | 共享 contracts 包 | `new_app/packages/contracts/` | 包 | 架构负责人 |
| D0.4 | 共享 domain/observability 包 | `new_app/packages/domain/`、`packages/observability/` | 包 | 架构负责人 |
| D0.5 | 七个服务骨架 | `new_app/services/*` | 代码骨架 | 各服务负责人 |
| D0.6 | 前端骨架 | `new_app/web/` | Vite 应用 | 前端负责人 |
| D0.7 | Compose 开发环境 | `new_app/deploy/compose/docker-compose.yml` | 配置 | DevOps |
| D0.8 | CI 流水线 | `.github/workflows/new-app-ci.yml`（或等价） | 配置 | DevOps |
| D0.9 | PROVENANCE 规范 | `new_app/PROVENANCE.md` | 文档 | 架构负责人 |
| D0.10 | ADR-000/001 | `new_app/docs/adr/` | 文档 | 架构负责人 |
| D0.11 | 开发环境说明 | `new_app/README.md` | 文档 | 架构负责人 |

> `new_app/docs` 已存放架构方案与开发计划；ADR 可放 `new_app/docs/adr/`。

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M0-01 | 创建目录骨架与命名规范 | 项目负责人（兼架构） | — | 目录树、命名约定 | 2026-11-12 |
| M0-02 | 初始化 Python workspace | 项目负责人（兼后端） | — | pyproject、uv.lock | 2026-11-13 |
| M0-03 | 建立 contracts 包与 schema 占位 | 项目负责人（兼架构） | — | OpenAPI/JSON Schema 占位 | 2026-11-14 |
| M0-04 | 建立 domain/observability 共享包 | 项目负责人（兼架构） | — | 包骨架 | 2026-11-14 |
| M0-05 | 七服务骨架与 `/healthz` | 项目负责人（兼后端） | — | 可启动服务 | 2026-11-15 |
| M0-06 | 前端 Vite/React/TS 骨架 | 项目负责人（兼前端） | — | 可启动页面 | 2026-11-15 |
| M0-07 | Compose 基础设施（Postgres/MinIO/Redis） | 项目负责人（兼 DevOps） | — | compose 文件 | 2026-11-16 |
| M0-08 | WSL 轻量 K8s PoC 与选型记录 | 项目负责人（兼 DevOps） | — | WSL K8s 记录 | 2026-11-16 |
| M0-09 | CI：lint/typecheck/单测/契约/import 检查 | 项目负责人（兼 DevOps） | — | CI 配置 | 2026-11-17 |
| M0-10 | PROVENANCE 与 ADR 模板 | 项目负责人（兼架构） | — | 模板与示例 | 2026-11-17 |
| M0-11 | 开发环境说明与验收演示 | 项目负责人 | — | README、演示记录 | 2026-11-18 |

## 6. 接口与契约

本阶段只建立契约骨架，不定义业务字段细节；要求：

- `packages/contracts/openapi/public.yaml` 存在，包含 `info`、`servers`、`paths: {}` 占位。
- `packages/contracts/openapi/internal.yaml` 存在。
- `packages/contracts/schemas/` 存在，预留 `recipe-package-2.0.json`、`run-manifest-1.0.json`。
- 所有服务健康检查统一返回：

```json
{"status": "ok", "service": "<name>", "version": "0.0.0"}
```

- 服务端口约定：

| 服务 | 端口 |
|---|---|
| api-gateway | 8000 |
| orchestration | 8001 |
| ocr | 8002 |
| agent | 8003 |
| sandbox | 8004 |
| recipe-registry | 8005 |
| review | 8006 |
| web | 5173（dev） |

## 7. 验收标准

### 7.1 功能

- [ ] `new_app` 目录结构与架构方案 4.6 一致。
- [ ] 七个服务均可启动，`/healthz` 返回 200。
- [ ] 前端 `pnpm dev` 可启动，显示空白骨架页。
- [ ] `docker compose up` 可启动 Postgres/MinIO/Redis 与服务占位。
- [ ] 所有服务能读取 `.env.example` 中的配置。
- [ ] WSL 内轻量 K8s 可启动，七个服务可部署并通过健康检查。
- [ ] 本地对象存储使用 MinIO，服务可上传/下载产物。
- [ ] 公开 API 路径统一以 `/v1` 开头，内部 API 使用 `/internal`。

### 7.2 质量

- [ ] lint/typecheck 通过。
- [ ] 单测框架可运行（允许 0 业务用例，但至少 1 个健康检查用例）。
- [ ] 契约文件可被解析/校验。
- [ ] `import-linter` 生效：`new_app` 不得 import `metal_doc_agent`/`hanson_api`。
- [ ] CI 在 PR 上自动运行并通过。

### 7.3 文档

- [ ] `new_app/README.md` 包含启动步骤、端口、目录说明。
- [ ] `requirements.md`、`decision-log.md` 已归档并可访问。
- [ ] `PROVENANCE.md` 模板可用。
- [ ] ADR-000（绿地重构与旧代码只读）完成。
- [ ] ADR-001（微服务边界）完成。
- [ ] 文档索引链接完整。

### 7.4 安全与规范

- [ ] `.env.example` 不含真实密钥。
- [ ] `.gitignore` 覆盖数据、缓存、构建产物。
- [ ] 无旧代码复制残留的敏感配置。

## 8. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K0.1 目录与 workspace 就绪 | 2026-11-13 | 可安装依赖 |
| K0.2 服务骨架可启动 | 2026-11-15 | 七服务健康检查通过 |
| K0.3 Compose + MinIO 可启动 | 2026-11-16 | 本地一键环境 |
| K0.4 WSL K8s PoC 完成 | 2026-11-16 | 发行版选型记录 |
| K0.5 CI 绿 | 2026-11-17 | PR 门禁生效 |
| K0.6 验收 | 2026-11-18 | 验收记录签字 |

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| Python workspace 工具不兼容 Windows | 统一 uv；提供 PowerShell 脚本；CI 用 Linux |
| 服务骨架端口冲突 | 固定端口表；环境变量可覆盖 |
| Compose 镜像拉取慢 | 预拉取/镜像缓存；提供离线说明 |
| 契约占位被后续随意修改 | 契约变更必须走架构评审 |
| 旧代码被误 import | CI 加 import-linter 与 grep 检查 |
| WSL 资源不足/不支持 K8s | 先做资源评估；改用远程 Linux；方案不变 |
| 单人执行导致串行延期 | M0 重新基线；只做脚手架，不扩范围 |

## 10. 出口准则与回滚

**出口准则**

- 所有交付物完成并验收。
- 所有验收标准勾选。
- 项目负责人验收签字；外部模型服务器管理员按需确认。

**回滚**

- M0 不影响旧系统；如需回滚，删除/停用 `new_app` 分支即可。
- 旧代码未修改，无数据变更。

## 11. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 下一里程碑：[M1 核心领域与编排骨架](M1-core-domain-orchestration.md)

## 12. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q1 WSL K8s、Q6 MinIO、Q7 `/v1`、Q8 单人约束 | 项目负责人 |
| v1.2 | 2026-11-11 | 记录 M0 执行结果；补充第三模型地址 `192.168.1.35` | 项目负责人 |
| v1.3 | 2026-11-11 | 记录 WSL Compose 实测通过、端口调整与 K8s 网络受限情况 | 项目负责人 |
| v1.4 | 2026-11-11 | kind 集群创建成功；节点 Ready、命名空间 Active；七服务 K8s 部署列为待完成 | 项目负责人 |
| v1.5 | 2026-11-11 | 七服务与基础设施已部署到 kind；集群内健康与 NodePort 端到端验证通过；K8s 部署项收口 | 项目负责人 |

---

## 13. 执行记录（2026-11-11）

### 13.1 已完成

| 项 | 结果 |
|---|---|
| 分支 | 已创建并切换到 `new_doc_parse` |
| 旧代码清理 | `apps/`、`metal-doc-agent/`、`packages/`、`e2e/`、`infra/`、`deploy/`、`docs/`、`training/`、`metal-standard-agent-plan/`、`markdown/` 已归档到 `legacy/` |
| 根配置 | 旧 `package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`、`README.md`、`.dockerignore` 已归档到 `legacy/root/` |
| 新目录 | `new_app/` 七个服务骨架、`packages/`、`web/`、`deploy/`、`tests/`、`scripts/` |
| 契约 | 公开/内部 OpenAPI 占位、配方包与 RunManifest JSON Schema |
| 服务 | 七服务 `/healthz`、`/readyz` 可启动 |
| 前端 | Vite + React + TS 骨架，核心页面占位；无登录/租户/工作区 |
| 本地基础设施 | Compose：Postgres/MinIO/Redis + 七服务 |
| CI | `.github/workflows/new-app-ci.yml`（Python + Web） |
| 文档 | 架构、需求、决策记录、整体计划、M0–M8 计划均在 `new_app/docs/` |
| 第三模型地址 | `192.168.1.35` 已加入 Q1 三地址切换方案与配置示例 |

### 13.2 已验证

| 验证 | 结果 |
|---|---|
| Python 编译 | `python -m compileall` 通过 |
| Python 测试 | `pytest` 3 passed |
| Ruff | `ruff check` 通过 |
| 前端类型检查 | `npm run typecheck` 通过 |
| 前端构建 | `npm run build` 通过 |
| Compose YAML | Python YAML 解析通过，10 个 service |
| Compose 实机启动 | WSL Docker Compose 实际启动 10 个容器 |
| 七服务健康 | `18000–18006/healthz` 全部返回 `status=ok` |
| 基础设施 | MinIO 存活、Postgres `pg_isready`、Redis `PONG` |
| WSL kind 集群 | 集群 `hanson` 创建成功；节点 `hanson-control-plane` 为 `Ready`（v1.30.0） |
| 命名空间 | `hanson-standard` 状态 `Active` |
| K8s 镜像加载 | `hanson-new-app:local`、`postgres:16-alpine`、`minio/minio:latest`、`redis:7-alpine` 已导入节点 containerd |
| K8s 部署 | 10 个 Pod 全部 `Running 1/1`；10 个 Service 创建完成；`api-gateway` 以 NodePort `30080` 暴露 |
| K8s 集群内健康 | 七服务 `/healthz` 全部 `status=ok`；Postgres/Redis TCP 可连；MinIO `/minio/health/live` 返回 200 |
| K8s 端到端 | 经 NodePort 上传 → run → `STRUCTURED_READY` → 结果 `Q355B / Rm=470 MPa`，四个阶段 `completed` |
| 旧包 import 检查 | `new_app` 无旧包 import |

### 13.3 待完成（验收前）

- [ ] CI 在远端 `new_doc_parse` 分支跑通。
- [ ] 项目负责人最终验收签字。

> WSL Docker Compose 已实测通过；WSL kind 集群与命名空间已就绪。K8s 选型：kind v0.24.0 + kindest/node v1.30.0（经国内代理下载 kind，kubectl 经 Google 存储源下载）。  
> Compose 主机端口：服务 `18000–18006`、Postgres `15432`、MinIO `19000/19001`、Redis `16379`。这样避开了本机 SonarQube 的 `9000`、旧平台的 `8000` 等已占用端口。  
> K8s 复现脚本：`scripts/dev/k8s-deploy.sh`（加载镜像 + 应用清单 + 等待就绪）、`k8s-smoke.sh`（集群内健康）、`k8s-e2e.sh`（上传到结果主链路）。  
> `kind load docker-image` 在 Docker 使用 containerd image store 时会因 `--all-platforms` 报 digest 缺失，脚本已改为 `docker save --platform linux/amd64 | ctr images import`。
