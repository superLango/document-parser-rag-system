# M5 里程碑详细执行计划：Qwen Agent Runtime 与路由/审核

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2027-01-14 ~ 2027-02-03  
> 主责角色：项目负责人（兼 Agent/算法）  
> 协作角色：外部模型服务器管理员（按需）、业务/领域专家（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0](M0-project-scaffold.md)、[M1](M1-core-domain-orchestration.md)、[M3](M3-recipe-registry.md)  
> 当前状态：已完成（M5 核心验收通过，2026-11-11；并发 4 组合压测留待 M8）

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
| v1.2 | 2026-11-11 | 完成 M5 实现与验证，回填执行记录、指标与偏差 | 项目负责人 |

---

## 14. 执行记录（2026-11-11）

### 14.1 交付物

| # | 交付物 | 状态 | 位置 |
|---|---|---|---|
| D5.1 | agent-service | 完成 | `services/agent/` |
| D5.2 | Harness/Session | 完成 | `harness.py`、`session.py` |
| D5.3 | Context Manager | 完成 | `services/agent/context/` |
| D5.4 | 分段器 | 完成 | `services/agent/segmentation.py` |
| D5.5 | 工具注册 | 完成 | `services/agent/tools/` |
| D5.6 | Prompt | 完成 | `services/agent/prompts/` |
| D5.7 | Model Gateway | 完成 | `services/agent/model_gateway.py` |
| D5.8 | RouterAgent | 完成 | `services/agent/agents/router.py` |
| D5.9 | ReviewAgent | 完成 | `services/agent/agents/review.py` |
| D5.10 | review-service | 完成 | `services/review/` |
| D5.11 | 评测报告 | 完成 | `docs/reports/M5-agent-eval.md` |
| D5.12 | 窗口基准报告 | 完成 | `docs/reports/M5-window-benchmark.md` |
| D5.13 | 模型三地址切换报告 | 完成 | `docs/reports/M5-model-failover.md` |
| D5.14 | 看门狗测试报告 | 完成 | `docs/reports/M5-watchdog.md` |

### 14.2 实现摘要

- 模型：`Qwen3.6-35B-A3B-NVFP4` @ `192.168.1.35:9988`，`max-model-len=131072`、`max-num-seqs=4`、NVFP4、`gpu-memory-utilization=0.40`。
- Agent API：`POST /internal/agent:run`、`POST /internal/agent:resume`、`GET /internal/agent/health`。
- Harness：工具白名单、max_steps/max_tool_calls/wall_time、循环检测、JSON/schema 校验、SQLite 检查点与恢复。
- Context：vLLM `/tokenize` 真实 tokenizer；L1–L3 压缩；证据/表头/单位/schema/objective/decisions 不变量；超限抛 `ContextOverflow`。
- 分段：table/page/schema/token 分段；确定性合并；冲突显式返回。
- Model Gateway：三地址、10 秒防抖切换、30 秒冷却回切、4xx 不切换、JSON 修复一次、usage 累计。
- RouterAgent：catalog 约束、确定性 guard、模型不可用降级。
- ReviewAgent + review-service：规则链（12 条规则）+ 可选模型 Finding；模型不可用仅规则审核并标记 `degraded`。
- 编排：review 阶段从 fake 切换为真实 review-service；持久化 `review_reports`/`findings`；`REVIEW_USE_FAKE` 可回滚。
- 看门狗：加载期 floor 8192 MiB、测试期 floor 4096 MiB；加载守护就绪自动退出。

### 14.3 验证记录

| 验证 | 命令/报告 | 结果 |
|---|---|---|
| Agent/Review 单元测试 | `pytest tests/integration/agent -q` | 26 passed |
| Compose E2E（真实模型审核） | `scripts/dev/e2e-check.sh <doc>` | STRUCTURED_READY；1 表 2 记录；review 1.7 s；`review.v1`；`degraded=false` |
| K8s E2E（真实模型审核） | `scripts/dev/k8s-e2e.sh tests/fixtures/mechanical.md` | STRUCTURED_READY；沙箱 Job 5.4 s；review 1.1 s；`review.v1`；`review_reports` 落库 1 条 |
| 路由评测 | `scripts/benchmark/router_eval.py` | Agent 1.0（5/5） vs 确定性 0.6（3/5） |
| 审核评测 | `scripts/benchmark/review_eval.py` | 召回 1.0，误报 0.0 |
| 窗口基准 | `scripts/benchmark/window_benchmark.py` | 32K 11.5 s / 64K 10.1 s / 128K 26.4 s；看门狗未触发 |
| 三地址切换 | `test_model_gateway.py` | 10 s 切换、短抖动不回切、冷却回切、全故障降级 |
| 看门狗 | `test_watchdog.py`、加载/基准日志 | 4 passed；加载 floor 8192、测试 floor 4096 |
| 上下文/分段 | `test_context.py`、`test_segmentation.py` | 截断 0、关键事实丢失 0、合并确定性 |
| 检查点恢复 | `test_harness.py` | 100% |

### 14.4 与计划的偏差

1. **primary/secondary 已配置但当前不可用**：M6 补齐旧代码地址（`39.107.239.208:35035` / `192.168.188.75:9991`）；启动/周期探测会把不可达或模型不匹配的端点标记为 down，agent 自动使用 tertiary `192.168.1.35:9988`。真实三地址切换需旧地址服务同一模型。
2. **确定性 matcher 与新金标集口径不一致**：`hardness_v1` 与 `mechanical_properties_v1` 共享 `mechanical_properties` profile，确定性 matcher 在 2 张机械表上误选 hardness；RouterAgent 已纠正。**M6 已修复**：`matcher.py` 增加低覆盖惩罚，确定性 matcher 达到 5/5；M3 route parity 报告更新为 recipe 3/5、status 5/5（2 例有意纠正）。
3. **窗口基准为单请求**：32K/64K/128K 三组均有数据，但“并发 4 × 三窗口 × 共跑模型”组合压测留待 M8；D-005 已标注。
4. **128K 实际 119,970 tokens**：为输出预留空间，服务器上限 131,072。
5. **ReviewAgent 在合法样本上返回 0 条 Finding**：符合预期；模型语义召回需注入矛盾样本，M5 以规则召回 1.0 作为验收依据。
6. **Router/Review 单次结构化调用**：多轮工具修复留给 M6 Repair/Triage；通用 Harness 已具备工具循环。

### 14.5 验收结论

- [x] Agent 可运行 RouterAgent 并返回结构化决策。
- [x] Agent 可运行 ReviewAgent 并返回 Finding（规则链 + 可选模型）。
- [x] 会话可检查点/恢复。
- [x] 上下文压缩后关键事实不丢失。
- [x] 长文档自动分段并可合并。
- [x] 模型不可用时降级确定性路由/规则审核。
- [x] 非法 JSON 可修复一次，仍失败则结构化报错。
- [x] 主地址 10 秒切换、备/第三地址轮询、短抖动不回切、恢复回切（单元测试）。
- [x] 32K/64K/128K 三组窗口均有基准数据（单请求；并发 4 待 M8）。
- [x] 看门狗低于阈值终止测试进程，模型服务器保持可用。
- [x] 路由准确率 1.0 ≥ 确定性基线 0.6。
- [x] 审核召回 1.0 ≥ 0.95；误报 0.0 ≤ 0.05。
- [x] 上下文截断率 0；关键事实丢失 0；断点恢复 100%；JSON 非法率 0（修复后）。
- [x] Agent README、Prompt 版本、工具权限矩阵、评测报告、上下文/分段说明。

### 14.6 后续事项

| 事项 | 里程碑/责任 |
|---|---|
| 修复 hardness/mechanical profile 冲突或提高 matcher 表头权重 | M6 配方评审 |
| 补齐 primary/secondary 模型地址并做真实三地址切换 | 部署阶段 |
| 并发 4 × 32K/64K/128K 组合压测 | M8 负载测试 |
| Agent 会话库迁移到共享存储（多副本） | 生产部署 |
| 注入语义矛盾样本，评估模型审核召回 | M6 评测 |
| 将看门狗事件接入监控/告警 | M8 |
