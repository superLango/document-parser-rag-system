# M1 里程碑详细执行计划：核心领域与编排骨架

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2026-11-19 ~ 2026-12-02  
> 主责角色：项目负责人（兼后端/架构/测试）  
> 协作角色：外部无（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0 项目启动与脚手架](M0-project-scaffold.md)  
> 当前状态：计划中（未开工）

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
