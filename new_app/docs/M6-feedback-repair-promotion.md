# M6 里程碑详细执行计划：反馈、修复、验证与版本晋升

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2027-02-08 ~ 2027-02-28  
> 主责角色：项目负责人（兼后端/Agent/沙箱）  
> 协作角色：外部业务/领域专家（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M4 沙箱](M4-sandbox-runtime.md)、[M5 Agent Runtime](M5-agent-runtime.md)  
> 当前状态：计划中（未开工；含春节假期，节点可按排班顺延）

---

## 1. 里程碑目标

打通人工反馈到版本晋升的完整闭环：

```text
用户反馈
  → 根因分析（Triage）
  → 修复提案（Repair）
  → 候选配方/引擎版本
  → 沙箱定向重解析 + 回归
  → VerificationPackage
  → 用户验证
      → 通过：原子晋升 stable
      → 不通过：丢弃候选，stable 不变
```

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| Feedback API | 创建、列表、详情、处理 |
| FeedbackTriageAgent | 复现、根因、修复范围 |
| RepairAgent | 候选包/补丁、测试计划 |
| 候选版本 | candidate recipe/engine 构建 |
| 沙箱验证 | 定向重解析 + 影响面回归 |
| VerificationPackage | before/after/diff/regression |
| Promotion | stable 通道原子切换 |
| Discard | 候选标记丢弃，stable 不变 |
| 审计 | run_events + promotions |
| E2E | 通过/拒绝两条路径 |

### 2.2 不做

- 不做前端页面（M7）。
- 不做配方编辑器。
- 不做多租户/权限。
- 不做旧 selfheal 服务迁移。
- 不做自动全量重跑（只做定向 + 抽样回归）。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M4 完成 | 沙箱可执行、可验证 |
| M5 完成 | Triage/Repair Agent 可调用 |
| M3 完成 | 配方版本/通道 |
| 用户反馈样本 | 至少 10 条真实/模拟反馈 |
| 回归集 | 影响面 + 金标样本 |
| 审批规则 | 谁可 approve（本期为 operator 字符串） |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D6.1 | Feedback 服务/API | `services/orchestration/feedback/` | 代码 | 架构/QA |
| D6.2 | TriageAgent | `services/agent/agents/triage.py` | 代码 | 算法 |
| D6.3 | RepairAgent | `services/agent/agents/repair.py` | 代码 | 算法 |
| D6.4 | 候选版本构建 | `services/recipe_registry/candidate/` | 代码 | 架构 |
| D6.5 | VerificationPackage | `services/orchestration/verification/` | 代码 | QA |
| D6.6 | Promotion/Discard | `services/orchestration/promotion/` | 代码 | 架构 |
| D6.7 | 审计事件 | `run_events`/`promotions` | 数据 | QA |
| D6.8 | E2E 测试 | `new_app/tests/e2e/feedback_loop/` | 测试 | QA |
| D6.9 | 运维手册 | `new_app/docs/runbooks/feedback-repair.md` | 文档 | DevOps |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M6-01 | Feedback 模型/API | 后端 | 架构 | API | 2027-02-08 |
| M6-02 | 反馈去重/状态机 | 后端 | QA | 状态流转 | 2027-02-10 |
| M6-03 | TriageAgent | Agent | 算法/业务 | 根因输出 | 2027-02-13 |
| M6-04 | RepairAgent | Agent | 算法/沙箱 | 候选修复 | 2027-02-16 |
| M6-05 | 候选包构建/校验 | 后端 | 配方/沙箱 | candidate | 2027-02-18 |
| M6-06 | 定向重解析 + 回归 | 后端 | 沙箱/QA | VerificationPackage | 2027-02-21 |
| M6-07 | Promotion 原子切换 | 后端 | 架构 | promote | 2027-02-23 |
| M6-08 | Discard 流程 | 后端 | QA | discard | 2027-02-24 |
| M6-09 | E2E 通过/拒绝 | QA | 全体 | E2E 报告 | 2027-02-27 |
| M6-10 | 验收 | PM | 全体 | 验收记录 | 2027-02-28 |

## 6. 接口与契约

### 6.1 Feedback API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/feedback` | 创建反馈 |
| GET | `/v1/feedback` | 列表（状态/文档） |
| GET | `/v1/feedback/{id}` | 详情 + 消息 + 根因 |
| POST | `/v1/feedback/{id}/process` | 触发 Triage/Repair |
| GET | `/v1/feedback/{id}/verification` | 验证包 |
| POST | `/v1/feedback/{id}/verify` | `{decision: approve|reject, reason}` |

### 6.2 Feedback 状态

```text
open → processing → proposed → verifying → verified → promoted
                                      └→ discarded
                                      └→ needs_more_info
```

### 6.3 VerificationPackage

```json
{
  "proposal_id": "...",
  "before_run": "run-...",
  "after_run": "run-...",
  "diff": {
    "added": [],
    "removed": [],
    "changed": []
  },
  "regression": {
    "documents": 5,
    "field_f1_delta": 0.0,
    "new_errors": 0
  },
  "affected_targets": [],
  "user_summary": "...",
  "artifacts": []
}
```

### 6.4 Promotion

```text
POST /v1/feedback/{id}/verify {decision: approve}
  → 校验 verification 通过
  → 乐观锁读取 stable
  → 写 promotions
  → 原子更新 recipe_channels.stable / engine_channels.stable
  → 发 promotion.completed
```

拒绝：

```text
POST /v1/feedback/{id}/verify {decision: reject, reason}
  → candidate 标记 discarded
  → stable 不变
  → feedback 关闭
```

## 7. 根因与修复范围

| 根因 | 修复范围 |
|---|---|
| OCR 错误 | 文档级覆盖 / 重 OCR |
| 表格结构 | 表格修复规则 / 配方 |
| 配方绑定 | candidate recipe config |
| 模板 schema | template 新版本 |
| 模型抽取 | prompt/规则/候选配方 |
| 词典 | 词典数据 |
| 展示 | 前端/结果映射（不晋升） |

原则：

- 范围从小到大。
- 能改数据不改代码。
- 能改配方不改引擎。
- 引擎代码变更必须单独评审。

## 8. 验收标准

### 8.1 功能

- [ ] 反馈可创建、去重、查询、处理。
- [ ] Triage 输出根因 + 修复范围 + 证据。
- [ ] Repair 生成候选包/补丁 + 测试计划。
- [ ] 沙箱可定向重解析并生成 VerificationPackage。
- [ ] 用户 approve 后 stable 原子切换。
- [ ] 用户 reject 后 candidate 丢弃，stable 不变。
- [ ] 所有步骤有 run_events 审计。

### 8.2 质量

| 指标 | 门槛 |
|---|---|
| 通过路径 | E2E 通过 |
| 拒绝路径 | E2E 通过 |
| 晋升原子性 | 并发晋升无丢失 |
| 回归 | 不新增 error/critical |
| 目标修复 | 验证包明确显示目标已修复 |
| 审计 | 100% 关键事件 |

### 8.3 文档

- [ ] 反馈状态机说明。
- [ ] 根因分类说明。
- [ ] 验证包字段说明。
- [ ] 晋升/回滚/丢弃操作手册。
- [ ] E2E 报告。

## 9. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K6.1 Feedback API 可用 | 2027-02-10 | 创建/查询通过 |
| K6.2 Triage 可用 | 2027-02-13 | 根因输出 |
| K6.3 Repair 可用 | 2027-02-16 | 候选修复 |
| K6.4 验证包可用 | 2027-02-21 | before/after |
| K6.5 晋升/丢弃可用 | 2027-02-24 | 两条路径 |
| K6.6 验收 | 2027-02-28 | E2E 通过 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 根因误判 | 证据强制；人工复核；置信度门槛 |
| 修复引入回归 | 影响面回归 + 金标抽样；不通过即丢弃 |
| 候选版本污染 stable | 两阶段提交；乐观锁；审批记录 |
| 验证包过大 | 只展示影响字段 + 摘要；完整产物链接 |
| 反馈重复 | 去重键；合并策略 |
| 春节假期 | 计划预留缓冲；关键节点提前确认 |

## 11. 出口准则与回滚

**出口准则**

- 通过/拒绝两条路径 E2E 通过。
- 晋升/回滚/丢弃演练完成。
- 审计完整。
- 业务/架构/QA/PM 验收。

**回滚**

- 晋升错误：`rollback` 回上一 stable。
- 关闭反馈入口：不影响已有解析。
- 候选丢弃不影响 stable。

## 12. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M5](M5-agent-runtime.md)
- 下一里程碑：[M7 前端核心页面](M7-frontend-core-pages.md)

## 13. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q8 单人角色；引用 Q1/Q2 决策 | 项目负责人 |
