# M5 里程碑详细执行计划：Qwen Agent Runtime 与路由/审核

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2027-01-14 ~ 2027-02-03  
> 主责角色：项目负责人（兼 Agent/算法）  
> 协作角色：外部模型服务器管理员（按需）、业务/领域专家（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0](M0-project-scaffold.md)、[M1](M1-core-domain-orchestration.md)、[M3](M3-recipe-registry.md)  
> 当前状态：计划中（未开工）

---

## 1. 里程碑目标

建立独立 `agent-service`，承载 Qwen Agent Runtime，并落地前两个 Agent 与审核服务：

- Harness：会话、工具循环、护栏、检查点。
- Context：真实 tokenizer、窗口预算、L1–L3 压缩、无损不变量。
- 长任务分段：table/page/schema/token 策略 + Map-Reduce。
- RouterAgent：配方/模板路由。
- ReviewAgent + review-service：规则校验、模型审核、Finding 聚合。
- 评测：路由准确率、审核召回/误报、截断率、断点恢复、token/延迟。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| agent-service | 独立服务、`/internal/agent:run`、`/resume` |
| Harness | Session/Step/ToolCall/Guardrails |
| Context | token 预算、压缩、不变量检查 |
| 分段 | table/page_range/schema_category/token_budget |
| 工具 | recipe/table/records/evidence/sandbox/review/human |
| Prompt | router/review 版本化 |
| Model Gateway | 三地址（旧代码两种 + `192.168.1.35`）、连续 10 秒失败切换、防抖/回切、重试、熔断、usage |
| 模型版本 | Qwen 固定 35B；其他模型版本参考旧代码 |
| 窗口基准 | 并发 4、与 GLM/Layout 共跑；32K/64K/128K 评分选优 |
| 内存看门狗 | 模型服务器剩余内存低于阈值时终止测试进程 |
| RouterAgent | 路由决策 + 原因 |
| ReviewAgent | 语义审核 |
| review-service | 规则链、Finding、报告 |
| 评测 | 路由/审核/上下文/断点 |

### 2.2 不做

- 不做 RepairAgent/TriageAgent（M6）。
- 不做反馈/晋升（M6）。
- 不做前端 Agent 调试页（M7 可选）。
- 不做模型训练/LoRA。
- 不做多租户/权限。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M0 完成 | 服务骨架、contracts |
| M1 完成 | 编排可调用 Agent/审核阶段 |
| M3 完成 | 配方目录、RecipeRef |
| Qwen 服务 | 模型服务器上的 Qwen 35B；三种访问地址（含 `192.168.1.35`，Q1） |
| 模型操作 | 部署/启停/调参/压测在模型服务器执行（D-002） |
| 窗口/并发 | 并发 4 场景；32K/64K/128K 可测（Q2） |
| 内存看门狗 | 模型服务器内存监控可用；阈值可配置（Q2） |
| 审核样本 | 注入错误集、业务验收样本 |
| Prompt 基线 | 旧 Qwen prompt 参考 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D5.1 | agent-service | `services/agent/` | 服务 | 架构/QA |
| D5.2 | Harness/Session | `services/agent/harness.py`、`session.py` | 代码 | 架构 |
| D5.3 | Context Manager | `services/agent/context/` | 代码 | 架构 |
| D5.4 | 分段器 | `services/agent/segmentation.py` | 代码 | 架构 |
| D5.5 | 工具注册 | `services/agent/tools/` | 代码 | 架构 |
| D5.6 | Prompt | `services/agent/prompts/` | 文本 | 业务/架构 |
| D5.7 | Model Gateway | `services/agent/model_gateway.py` | 代码 | 架构 |
| D5.8 | RouterAgent | `services/agent/agents/router.py` | 代码 | 算法 |
| D5.9 | ReviewAgent | `services/agent/agents/review.py` | 代码 | 算法 |
| D5.10 | review-service | `services/review/` | 服务 | 架构/QA |
| D5.11 | 评测报告 | `new_app/docs/reports/M5-agent-eval.md` | 报告 | PM/架构 |
| D5.12 | 窗口基准报告 | `new_app/docs/reports/M5-window-benchmark.md` | 报告 | 项目负责人 |
| D5.13 | 模型三地址切换报告 | `new_app/docs/reports/M5-model-failover.md` | 报告 | 项目负责人 |
| D5.14 | 看门狗测试报告 | `new_app/docs/reports/M5-watchdog.md` | 报告 | 项目负责人 |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M5-01 | Agent 契约与会话模型 | 项目负责人（兼架构） | — | DTO/表 | 2027-01-14 |
| M5-02 | Harness 主循环 | 项目负责人（兼 Agent） | — | harness | 2027-01-16 |
| M5-03 | Session/检查点/恢复 | 项目负责人（兼 Agent） | — | session store | 2027-01-18 |
| M5-04 | Token 预算与压缩 | 项目负责人（兼 Agent） | — | context manager | 2027-01-20 |
| M5-05 | 长任务分段 | 项目负责人（兼 Agent） | — | segmentation | 2027-01-21 |
| M5-06 | 工具注册与权限 | 项目负责人（兼 Agent） | — | tools | 2027-01-23 |
| M5-07 | Model Gateway：三地址 + 10 秒切换 | 项目负责人（兼 Agent） | — | gateway | 2027-01-25 |
| M5-08 | 窗口基准（32K/64K/128K，并发 4） | 项目负责人（兼 Agent） | — | 基准报告 | 2027-01-27 |
| M5-09 | 内存看门狗与压测 | 项目负责人（兼 Agent） | — | 看门狗报告 | 2027-01-28 |
| M5-10 | RouterAgent + 评测 | 项目负责人（兼 Agent） | — | router | 2027-01-30 |
| M5-11 | ReviewAgent + 规则链接 | 项目负责人（兼 Agent） | — | review | 2027-02-01 |
| M5-12 | 评测报告与验收 | 项目负责人 | — | 报告 | 2027-02-03 |

## 6. 接口与契约

### 6.1 Agent API

```text
POST /internal/agent:run
POST /internal/agent:resume
```

### 6.2 AgentTask

```json
{
  "task_id": "...",
  "trace_id": "...",
  "role": "router|review|repair|triage",
  "objective": "...",
  "inputs": {},
  "output_schema": {},
  "tools": ["get_table_summary", "..."],
  "budget": {"max_steps": 24, "max_tokens": 64000}
}
```

### 6.3 AgentResult

```json
{
  "task_id": "...",
  "session_id": "...",
  "status": "completed|waiting_human|failed",
  "output": {},
  "usage": {"prompt_tokens": 0, "completion_tokens": 0},
  "steps": 6,
  "artifacts": []
}
```

### 6.4 上下文不变量

压缩后必须保留：

- 证据 ID、表头路径、单位、条款 ID。
- 输出 schema、字段集合。
- 当前任务目标、已确认决策。
- 丢弃内容必须有 `ArtifactRef` 或摘要。

### 6.5 Router 输出

```json
{
  "assignments": [
    {
      "table_id": "T1",
      "recipe_id": "mechanical_properties",
      "version": "2.0.0",
      "confidence": 0.92,
      "reasons": ["signature=0.91", "token_overlap=0.88"]
    }
  ],
  "fallback": "human|generic|fail",
  "confidence": 0.92
}
```

### 6.6 Review 输出

```json
{
  "findings": [
    {
      "category": "semantic",
      "severity": "error",
      "target": {"record_id": "...", "property": "Rm"},
      "observed": "250",
      "expected": "250 MPa",
      "evidence_refs": ["ev-..."],
      "confidence": 0.9
    }
  ]
}
```

## 7. 上下文与长任务要求

| 项 | 要求 |
|---|---|
| 窗口 | 并发 4、与 GLM/Layout 共跑，基准选择 32K/64K/128K；默认 64K |
| 模型访问 | 三地址；连续 10 秒失败自动切换；防抖/回切 |
| 模型版本 | Qwen 固定 35B；其他参考旧代码 |
| 看门狗 | 模型服务器剩余内存低于阈值时终止测试进程 |
| Tokenizer | 真实 tokenizer，禁止只按字符估算 |
| 压缩 | L1 70% / L2 85% / L3 95% |
| 溢出 | 强制分段 + 检查点，不截断 JSON |
| 分段 | table/page_range/schema_category/token_budget |
| 合并 | 确定性优先，冲突模型仲裁，无法仲裁转人工 |
| 恢复 | 从最后完成 segment 继续 |
| 护栏 | max_steps/max_tool_calls/wall_time/loop detection |

## 8. 验收标准

### 8.1 功能

- [ ] Agent 可运行 RouterAgent 并返回结构化决策。
- [ ] Agent 可运行 ReviewAgent 并返回 Finding。
- [ ] 会话可检查点/恢复。
- [ ] 上下文压缩后关键事实不丢失。
- [ ] 长文档自动分段并可合并。
- [ ] 模型不可用时降级确定性基线/规则审核。
- [ ] 非法 JSON 可修复一次，仍失败则结构化报错。
- [ ] 主地址不可达 10 秒后自动切换备地址；主/备均不可达后自动切换 `192.168.1.35`；短时抖动不切换；恢复后按配置回切。
- [ ] 32K/64K/128K 三组窗口均有基准数据，最终窗口回填 D-005。
- [ ] 看门狗在内存低于阈值时终止测试进程，模型服务器保持可用。

### 8.2 指标

| 指标 | 门槛 |
|---|---|
| 路由准确率 | ≥确定性基线 |
| 审核召回（注入错误） | ≥0.95 |
| 审核误报 | ≤0.05 |
| 上下文截断率 | 0 |
| 关键事实丢失 | 0 |
| 断点恢复 | 100% |
| 非法 JSON 率 | ≤0.1% |
| p95 延迟 | ≤基线 1.3× |
| token/任务 | ≤基线 1.2× |

### 8.3 文档

- [ ] Agent Runtime 设计说明。
- [ ] Prompt 版本说明。
- [ ] 工具权限矩阵。
- [ ] 评测报告（含失败样本）。
- [ ] 上下文压缩/分段说明。

## 9. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K5.1 契约/会话冻结 | 2027-01-14 | 评审通过 |
| K5.2 Harness 可跑 | 2027-01-18 | 单 Agent 冒烟 |
| K5.3 上下文/分段完成 | 2027-01-21 | 压缩不变量通过 |
| K5.4 RouterAgent 可用 | 2027-01-27 | 路由评测 |
| K5.5 ReviewAgent 可用 | 2027-01-30 | 审核评测 |
| K5.6 验收 | 2027-02-03 | 报告签字 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 模型窗口不足 | 可调窗口；分段；压缩；降级 |
| 模型输出不稳定 | schema 校验 + 一次修复 + 基线降级 |
| prompt 漂移 | prompt 版本化 + 评测门禁 |
| 长任务 token 成本高 | 分段预算；规则优先；缓存 |
| 审核误报高 | 注入错误集调参；确定性优先 |
| Agent 工具越权 | 工具白名单 + 权限矩阵 + 服务端校验 |
| 断点恢复复杂 | 每步/每段检查点；不可重放副作用 |

## 11. 出口准则与回滚

**出口准则**

- Router/Review 指标达标。
- 上下文/分段/恢复测试通过。
- 评测报告签字。
- 架构/业务/QA/PM 验收。

**回滚**

- 编排可关闭 Agent，回退确定性路由 + 规则审核。
- agent-service 可独立停用。
- 不影响 M4 沙箱与 M3 配方。

## 12. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M4 沙箱](M4-sandbox-runtime.md)
- 下一里程碑：[M6 反馈/修复/晋升](M6-feedback-repair-promotion.md)

## 13. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q1 模型三地址/Qwen 35B、Q2 窗口基准/看门狗、Q8 单人角色 | 项目负责人 |
