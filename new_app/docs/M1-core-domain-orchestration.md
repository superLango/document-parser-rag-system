# M1 里程碑详细执行计划：核心领域与编排骨架

> 文档版本：v1.4  
> 编制日期：2026-11-11  
> 计划周期：2026-11-19 ~ 2026-12-02  
> 主责角色：项目负责人（兼后端/架构/测试）  
> 协作角色：外部无（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0 项目启动与脚手架](M0-project-scaffold.md)  
> 当前状态：进行中（主链路已跑通，待收口）

---

## 1. 里程碑目标

打通标准拆分主链路的“骨架版”：

```text
上传文档 → 创建 run → OCR（fake）→ 路由（fake）→ 沙箱（fake）→ 审核（fake）→ 结果读取
```

本阶段只验证**领域模型、状态机、API、事件、幂等、恢复**，不接真实 OCR/配方/沙箱/模型。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| 领域模型 | Document、DocumentVersion、Run、RunStage、RunEvent、Artifact、ReviewReport、Finding、Feedback（先建表，不做闭环） |
| 数据库 | Postgres schema + migration |
| 网关 | `/v1/documents`、`/v1/runs`、`/v1/runs/{id}`、`/v1/runs/{id}/events`、`/v1/runs/{id}/result` |
| 编排 | Run 状态机、阶段执行、检查点、重试、取消、幂等 |
| Fake 适配器 | fake OCR、fake sandbox、fake review |
| 事件 | run_events 写入、SSE 推送 |
| 产物 | 对象存储写入/读取、artifact manifest |
| 测试 | 单元、集成、API 契约 |

### 2.2 不做

- 不接真实 GLM OCR / Layout。
- 不实现表格、矩阵、条款算法。
- 不实现配方包/注册中心。
- 不实现真实沙箱。
- 不实现 Agent/模型调用。
- 不实现反馈/修复/晋升闭环。
- 不做前端页面（只保证 API 可用）。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M0 完成 | 服务骨架、contracts、compose、CI |
| 数据库可用 | Compose Postgres |
| 对象存储可用 | Compose MinIO |
| 契约基线 | `packages/contracts` |
| 状态机设计评审 | 架构负责人确认 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D1.1 | 领域模型 | `services/orchestration/domain/` | 代码（后续实现） | 架构 |
| D1.2 | 数据库迁移 | `services/orchestration/migrations/` | SQL/Alembic | 架构/DevOps |
| D1.3 | 编排状态机 | `services/orchestration/workflows/` | 代码 | 架构 |
| D1.4 | 公开 API | `services/api_gateway/routers/` | FastAPI | 架构/QA |
| D1.5 | Fake 适配器 | `services/orchestration/adapters/fake/` | 代码 | QA |
| D1.6 | 事件/SSE | `services/orchestration/events/`、网关 SSE | 代码 | QA |
| D1.7 | RunManifest | `packages/contracts/schemas/run-manifest-1.0.json` | Schema | 架构 |
| D1.8 | OpenAPI | `packages/contracts/openapi/public.yaml` | 契约 | 架构 |
| D1.9 | 集成测试 | `new_app/tests/integration/` | 测试 | QA |
| D1.10 | 主链路演示 | `new_app/docs/demos/M1-demo.md` | 文档 | PM |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M1-01 | 领域模型与字段评审 | 后端 | 业务专家/架构 | 模型定义 | 2026-11-20 |
| M1-02 | 数据库 schema 与迁移 | 后端 | DevOps | 迁移脚本 | 2026-11-22 |
| M1-03 | 文档上传/查询 API | 后端 | QA | API + 测试 | 2026-11-23 |
| M1-04 | Run 创建/查询 API | 后端 | QA | API + 测试 | 2026-11-24 |
| M1-05 | 编排状态机与阶段执行 | 后端 | 架构 | 状态机代码 | 2026-11-26 |
| M1-06 | 检查点/重试/取消/幂等 | 后端 | 架构/QA | 机制 + 测试 | 2026-11-27 |
| M1-07 | Fake OCR/沙箱/审核适配器 | 后端 | QA | fake 实现 | 2026-11-27 |
| M1-08 | 事件写入与 SSE | 后端 | 前端/QA | SSE 可用 | 2026-11-28 |
| M1-09 | 产物存储与 RunManifest | 后端 | 架构 | 产物读取 | 2026-11-29 |
| M1-10 | 集成测试与演示 | QA | 后端/前端 | 测试报告/演示 | 2026-12-02 |

## 6. 接口与契约

### 6.1 公开 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/documents` | 上传文档 |
| GET | `/v1/documents` | 文档列表 |
| GET | `/v1/documents/{id}` | 文档详情 |
| DELETE | `/v1/documents/{id}` | 删除文档 |
| POST | `/v1/documents/{id}/runs` | 创建 run |
| GET | `/v1/runs/{id}` | run 状态 |
| GET | `/v1/runs/{id}/events` | SSE |
| GET | `/v1/runs/{id}/result` | 结果 |
| GET | `/v1/runs/{id}/timeline` | 时间线（可先返回 stages） |

### 6.2 状态机

必须实现架构方案 5.1/5.2 的状态与迁移；本阶段允许：

- `ROUTING` 使用 fake 规则。
- `SANDBOX_RUNNING` 使用 fake 产物。
- `REVIEWING` 使用 fake 规则审核。

### 6.3 幂等键

| 操作 | 键 |
|---|---|
| 上传 | `sha256 + filename` |
| 创建 run | `document_version + parse_profile + recipe_channel` |
| 阶段重试 | `run_id + stage + attempt` |

### 6.4 事件

必须写入 `run_events`，至少包含：

```text
run.created
run.stage.started
run.stage.completed
run.stage.failed
run.completed
run.failed
run.cancelled
artifact.created
```

## 7. 验收标准

### 7.1 功能

- [ ] 上传 `.md`/`.pdf` 成功，返回 document_id。
- [ ] 创建 run 后状态按 `RECEIVED → OCR_RUNNING → ... → STRUCTURED_READY` 流转。
- [ ] `GET /v1/runs/{id}` 返回当前状态、阶段、进度、错误码。
- [ ] `GET /v1/runs/{id}/result` 返回 fake 结构化结果。
- [ ] `GET /v1/runs/{id}/events` 可收到阶段事件。
- [ ] 重复上传/重复创建 run 幂等。
- [ ] 取消 run 后状态为 `cancelled`，不再执行后续阶段。
- [ ] 服务重启后可从最后完成阶段恢复。
- [ ] 所有公开 API 以 `/v1` 开头，内部 API 使用 `/internal`（Q7）。

### 7.2 质量

- [ ] 单元测试覆盖状态机、幂等、错误分类。
- [ ] 集成测试覆盖上传→run→结果。
- [ ] API 契约测试通过。
- [ ] 无旧包 import。
- [ ] 日志包含 `trace_id/run_id/stage`。
- [ ] 每个阶段写入 `run_stages` + artifact manifest。

### 7.3 文档

- [ ] 数据模型说明。
- [ ] 状态机图与迁移表。
- [ ] API 示例（curl/HTTP）。
- [ ] RunManifest 示例。
- [ ] M1 演示记录。

## 8. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K1.1 领域模型冻结 | 2026-11-20 | 评审通过 |
| K1.2 上传/run API 可用 | 2026-11-24 | Postman/curl 通过 |
| K1.3 状态机可跑 | 2026-11-27 | fake 阶段流转 |
| K1.4 SSE/产物可用 | 2026-11-29 | 前端可订阅 |
| K1.5 验收 | 2026-12-02 | 集成测试通过 |

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| 状态机过度设计 | 先实现主链路，分支后续补；每阶段必须有测试 |
| 数据库 schema 反复 | M1 只建核心表；后续 migration 增量 |
| Fake 与真实实现偏差 | Fake 必须实现同一端口；契约测试约束 |
| SSE 在代理后不可用 | 保留轮询兜底 |
| 幂等键设计不足 | 评审上传/run/阶段三类键 |

## 10. 出口准则与回滚

**出口准则**

- 所有验收标准满足。
- 主链路演示通过。
- 架构负责人、QA、PM 签字。

**回滚**

- 新服务可停用；旧系统未修改。
- 数据库可重建；无生产数据。
- 回滚不影响 M2 之前的开发。

## 11. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M0](M0-project-scaffold.md)
- 下一里程碑：[M2 OCR 服务与表格算法](M2-ocr-table-algorithms.md)、[M3 配方注册中心](M3-recipe-registry.md)

## 12. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q7 `/v1`、Q8 单人角色 | 项目负责人 |
| v1.2 | 2026-11-11 | 记录 M1 主链路执行结果与待收口项 | 项目负责人 |
| v1.3 | 2026-11-11 | 记录 K8s 端到端验证；修复 timeline 阶段排序与时钟回跳导致的负 duration | 项目负责人 |
| v1.4 | 2026-11-11 | 完成 M1 收口：Alembic 基线、阶段失败重试、文档删除级联；记录三项实测证据 | 项目负责人 |

---

## 13. 执行记录（2026-11-11）

### 13.1 已完成

| 项 | 结果 |
|---|---|
| 领域模型 | `documents/document_versions/runs/run_stages/run_events/artifacts/review_reports/findings/feedback` 已建表 |
| 编排状态机 | `RECEIVED → OCR_RUNNING → OCR_DONE → ROUTING → ROUTED → SANDBOX_RUNNING → PARSED → REVIEWING → REVIEW_PASSED → STRUCTURED_READY` |
| Fake 适配 | fake OCR、fake routing、fake sandbox、fake review |
| 检查点/恢复 | 阶段记录 + 事件；服务重启后 `resume_incomplete_runs` 跳过已完成阶段继续执行 |
| 取消 | `POST /v1/runs/{id}/cancel` 可终止运行 |
| 网关 | 文档上传/列表/详情/删除、run 创建/查询/取消、结果、时间线、事件、SSE |
| 对象存储 | MinIO S3 接口 + 本地文件降级 |
| 测试 | 9 passed（健康检查、状态机、存储、安全路径） |

### 13.2 实测证据

| 验证 | 结果 |
|---|---|
| 上传文档 | `README.md` 上传成功，返回 document_id 与 sha256 |
| 上传幂等 | 重复上传返回同一 document_id |
| 创建 run | 成功进入 `RECEIVED` |
| 主链路 | 自动流转到 `STRUCTURED_READY` |
| 结果 | `result.json` 返回 1 条记录 `Q355B / Rm=470 MPa` |
| 时间线 | `ocr/routing/sandbox/review` 四个阶段均 `completed` |
| 事件 | 9 条事件（8 条阶段事件 + `run.completed`） |
| SSE | 实时收到阶段事件与 `event: done` |
| 断点恢复 | 运行中重启编排，重启后继续并完成；修复了 `RUNNING → RUNNING` 重入问题 |
| 取消 | 运行中取消，状态变为 `CANCELLED` |
| K8s 端到端 | kind 集群内经 NodePort `30080` 完成上传 → run → `STRUCTURED_READY`；四阶段顺序正确、`duration_ms` 均为正 |
| 时钟回跳防护 | timeline 阶段改为按业务顺序输出；`finished_at` 取 `max(now, started_at)`，避免负 duration |
| Alembic 迁移 | 空库启动 orchestration 后 `alembic_version=0001_initial`；9 张业务表、外键与唯一约束齐全 |
| 阶段重试 | 注入 ocr 首次失败：`started(attempt=1)` → `failed(attempt=1, will_retry=true)` → `started(attempt=2)` → `completed(attempt=2)`，run 最终 `STRUCTURED_READY` |
| 删除级联 | 运行中删除文档返回 204、文档 GET 404；runs/stages/events/artifacts 由 `1/2/3/1` 变为 `0/0/0/0`，MinIO 中 run 目录已移除 |
| Compose 迁移 | `docker compose down -v` 后 `up -d --wait` 全部健康；上传与列表在空库上正常 |

### 13.3 收口结果（2026-11-11）

- [x] 数据库迁移：补齐 Alembic 基线 `0001_initial`（9 张表、级联外键、`run_stages(run_id, stage)` 与 `run_events(run_id, sequence)` 唯一约束）；`init_db` 启动时执行 `alembic upgrade head`，不再使用 `create_all`。
- [x] 失败重试：`STAGE_MAX_ATTEMPTS`（默认 2）+ `STAGE_RETRY_BACKOFF_SECONDS`（默认 0.5，按尝试次数线性退避）；每次失败写 `run.stage.failed` 事件，末次失败标记 `FAILED`。
- [x] 文档删除级联：删除前先取消未完成 run；子表由 `ON DELETE CASCADE` 清理；文档与产物对象同步删除。
- [ ] M1 前端联调：当前仅 API 可用，前端页面在 M7 重建。
- [ ] 真实 OCR/沙箱/审核：M2/M4/M5 接入，M1 使用 fake。

> 实测使用 WSL Docker Compose；服务端口 `18000–18006`，Postgres `15432`，MinIO `19000/19001`，Redis `16379`。
