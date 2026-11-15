# 审核 Agent 性能瓶颈专项优化计划

> 日期：2026-11-12
> 适用范围：review 服务、agent review 角色、编排审核阶段、前端审核展示
> 依据：[收尾测试报告](closeout-test-report.md)、`closeout-new-stage-timing.json`、E2E 运行数据

## 1. 现状与量化证据

审核 Agent 是当前完整链路的唯一显著瓶颈：

| 指标 | 实测 | 说明 |
|---|---|---|
| review 阶段 p50 | 38.27s | 60 份旧文档重建样本 |
| review 阶段 p95 | 117.38s | 与整体 p95 119.08s 基本一致 |
| review 占总耗时 | 3,076s / 3,204s ≈ 96% | 其余 OCR/路由/沙箱合计约 4% |
| PDF E2E review p50/p95 | 38.70s / 137.14s | 扫描件与文本件均受影响 |
| 失败重试 review p50/p95 | 41.30s / 134.72s | 大文档更明显 |
| 单文档模型发现数 | 516、544 条 | 与确定性规则发现叠加 |
| 同步判定 | `_review_stage` 阻塞等待模型 | run 无法提前完成 |

对照链路其余阶段：

| 阶段 | p50 | p95 |
|---|---|---|
| OCR（Markdown/文本层） | 0.48s | 1.13s |
| 路由 | 0.34s | 0.70s |
| 沙箱 | 1.06s | 2.05s |
| **审核（模型）** | **38.27s** | **117.38s** |

结论：解析主链路已经接近秒级，审核模型把端到端 p95 从约 3s 拉到约 120s。

## 2. 根因拆解

| # | 根因 | 证据 | 影响 |
|---|---|---|---|
| R1 | **同步阻塞**：编排在 review 阶段 `await _call_review`，完成后才落 `REVIEW_PASSED` | `services/orchestration/workflow.py` `_review_stage` | 端到端延迟直接等于模型延迟 |
| R2 | **输入放大**：把全部确定性 findings 注入模型输入；单文档可达 544 条 | `services/review/service.py` `_call_agent` → `deterministic_findings` | Prompt 变长、首 token 延迟上升 |
| R3 | **输出放大**：模型被要求逐条输出 findings，单文档 500+ 条 | `services/agent/agents/review.py` `REVIEW_SCHEMA` 无 maxItems | 生成阶段占主要时间 |
| R4 | **单点模型、无并发控制**：所有角色共享 tertiary 单卡端点，无信号量/队列 | `services/agent/config.py`、`model_gateway.py` | E2E 并发 3 时互相排队 |
| R5 | **全量调用、无采样/无缓存**：每次 run 都调用模型，相同内容重复调用 | `services/review/service.py`、`REVIEW_USE_AGENT=true` | 成本与延迟被放大 |
| R6 | **超时只做兜底，不做预算**：300s 超时才降级，期间一直阻塞 | `REVIEW_AGENT_TIMEOUT_SECONDS=300` | 长尾直接拖垮 p95 |
| R7 | **模型侧配置**：远程 tokenizer 额外网络调用；输出上限 4096；上下文 64K | `services/agent/config.py`、compose `AGENT_*` | 额外 RTT 与生成成本 |
| R8 | **门禁价值不匹配**：模型错误已降级为 warning，只有确定性错误阻断 | `services/review/service.py` 状态判定 | 同步等待模型并不提升门禁强度 |

## 3. 优化目标与 SLO

| 目标 | 指标 | 目标值 |
|---|---|---|
| 同步审核（确定性规则） | p95 | ≤ 200ms |
| run 完成延迟（不含 OCR） | p95 | ≤ 3s |
| AI 审核异步完成 | p95 | ≤ 60s |
| AI 审核成功率 | 成功/调用 | ≥ 95% |
| AI 审核降级率 | degraded/调用 | ≤ 5% |
| 模型调用量 | 相对当前 | 降低 ≥ 80% |
| Prompt 规模 | p95 tokens | ≤ 8K |
| 输出规模 | completion tokens | ≤ 1K，findings ≤ 30 |
| 质量门禁 | 确定性错误 | 0 回归 |

## 4. 优化方案

### Phase P0：立即解除阻塞（优先实施）

#### P0.1 同步路径只跑确定性规则，AI 审核异步化

- `review` 服务增加模式：
  - `deterministic`：只跑规则，立即返回；
  - `assist`：规则同步返回，AI findings 异步补充；
  - `shadow`：规则同步返回，AI 全量影子运行，不影响结果。
- 编排 `_review_stage` 只等待确定性报告，审核门禁仍按确定性错误阻断；AI 审核作为后台任务运行，完成后更新 review 报告（`stats.model_status = pending/completed/degraded`）。
- 运行状态不再等待模型：`REVIEW_PASSED → STRUCTURED_READY` 在规则审核完成后立即发生。
- API 兼容：`GET /v1/runs/{id}/review` 返回 `model_status`，前端显示“AI 审核中/已完成/已降级”。

**代码触点**
- `services/review/config.py`：新增 `mode`、`deadline_ms`、`sample_rate`、`max_findings`。
- `services/review/service.py`：拆分 `review_deterministic()` 与 `review_with_agent()`。
- `services/orchestration/workflow.py` `_review_stage`：同步规则 + 后台 AI 任务。
- `services/orchestration/models.py` / `ReviewReportRow`：优先复用 `stats` JSON，避免 schema 迁移。

**验收**
- 模型不可用/超时，run 仍能在确定性审核后完成；
- `model_status` 从 pending → completed/degraded 可见；
- 现有 18 项分支用例全部通过。

#### P0.2 风险采样与延迟预算

- 采样策略（默认 10%）：
  - 确定性 findings 含 error；或
  - 存在重复键、缺失单位、非数值、跨表同牌号冲突；或
  - 新配方版本首次运行、低置信度路由。
- `deadline_ms` 默认 8,000ms；超时立即返回 `degraded=true`，不阻塞 run。
- 高价值文档（error 或人工标记）强制 100% 调用。

**验收**
- 模型调用量下降 ≥ 80%；
- 强制样本 100% 覆盖；
- 降级率 ≤ 5%。

#### P0.3 Prompt 与输出瘦身

- 输入：
  - 确定性 findings 只保留前 20 条 + 聚合计数（按 rule/severity 分组）；
  - records 最多 20 条，仅保留被采样/有疑问记录；
  - evidence 只带被引用记录的证据；
  - 表格只带 header + 3 行样例；
  - 总字符上限 24K（硬截断并记录 `truncated=true`）。
- 输出：
  - `REVIEW_SCHEMA` 增加 `maxItems: 20`；
  - `observed/expected` 限制 120 字符；
  - `max_tokens=1024`；
  - 无发现时返回 `{"findings": []}`，不再生成解释性文本。

**验收**
- prompt tokens p95 ≤ 8K；
- completion tokens p95 ≤ 1K；
- 单文档 findings ≤ 30。

#### P0.4 结果缓存

- Key：`sha256(records + evidence + prompt_hash + model + recipe_version + ruleset_version)`。
- 存储：Redis（已有基础设施）或 review 服务本地 SQLite；TTL 24h。
- 命中直接返回缓存 findings，`stats.cache_hit=true`。

**验收**
- 同一文档重复运行模型调用为 0；
- 缓存命中率在回归集 ≥ 60%（旧文档重建场景）。

#### P0.5 配置开关

```env
REVIEW_MODE=deterministic        # deterministic | assist | shadow
REVIEW_USE_AGENT=false           # 同步模型调用总开关
REVIEW_AGENT_SAMPLE_RATE=0.1
REVIEW_AGENT_DEADLINE_MS=8000
REVIEW_AGENT_MAX_FINDINGS=20
REVIEW_AGENT_MAX_PROMPT_CHARS=24000
```

默认生产配置建议：`REVIEW_MODE=assist`、`REVIEW_USE_AGENT=false`（同步不等待），AI 审核由异步任务执行。

### Phase P1：模型与基础设施优化

1. **独立审核端点/模型**：review 角色固定到单独 endpoint，避免与 router/triage/repair 争抢；至少配置 `max_concurrency=2` 信号量。
2. **本地 tokenizer**：`AGENT_TOKENIZER_MODE=local`，去掉远程 tokenizer RTT。
3. **推理参数**：开启 prefix caching；固定 system prompt；`temperature=0`；`max_tokens=1024`；限制 `max-num-seqs` 防止单卡过载。
4. **队列化**：Redis/Arq/Celery 异步 worker；review 任务带优先级（error 文档优先）；队列深度与等待时间纳入监控。
5. **可观测性**：新增指标 `review_model_latency_ms`、`review_prompt_tokens`、`review_completion_tokens`、`review_findings`、`review_degraded`、`review_cache_hit`、`review_queue_wait_ms`。

### Phase P2：质量闭环与长期架构

1. **两阶段审核**：确定性规则先筛出“可疑记录”（低置信度、缺单位、重复键、跨表冲突），模型只审核这些记录，而不是整篇文档。
2. **Shadow 模式**：100% 文档影子调用模型，结果只落库不展示；用 2 周数据校准采样策略与模型 precision。
3. **人工反馈闭环**：审核页面支持“采纳/驳回”模型 finding；按 category 统计 precision，低于阈值的类别自动降级为 info 或停止调用。
4. **模型替换评估**：在相同 60 份样本上对比更小模型/量化版本，以“findings precision × 延迟 × 成本”选型。

## 5. 实施顺序与交付物

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| P0.1 | 异步审核模式 + `model_status` | 模型超时不影响 run 完成；18/18 分支通过 |
| P0.2 | 采样与 deadline 配置 | 调用量 -80%；降级率 ≤5% |
| P0.3 | Prompt/输出瘦身 | tokens 达标；findings ≤30 |
| P0.4 | 缓存层 | 重复运行 0 模型调用 |
| P0.5 | 配置与默认值 | 生产默认不同步等待模型 |
| P1 | 独立端点/队列/监控 | 异步 p95 ≤60s；队列可观测 |
| P2 | 两阶段 + shadow + 反馈 | 采样策略有数据依据；precision 可追踪 |

## 6. 验证方案

新增 `scripts/benchmark/review_agent_bench.py`：

- 输入：旧文档重建的 60 份 records/evidence 产物；
- 场景：
  1. `deterministic`：规则审核基线；
  2. `assist-sync`：当前同步模型审核（对照）；
  3. `assist-async`：P0 方案；
  4. `shadow`：全量影子。
- 指标：p50/p95、prompt/completion tokens、findings 数、降级率、缓存命中率、队列等待、模型调用次数。
- 质量抽检：随机 20 份人工核对模型 findings 的 precision；与现有 60 份对比结果对齐。

验收门槛：

- 确定性审核 p95 ≤200ms；
- 异步 AI 审核 p95 ≤60s、成功率 ≥95%；
- 模型调用量下降 ≥80%；
- 102 项单元/集成测试、18 项分支用例零回归；
- 审核门禁行为不变（确定性错误仍 REVIEW_FAILED）。

## 7. 风险、回滚与兼容

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 异步报告晚于 run 完成，消费方误判 | `model_status` 明示 pending；前端展示“AI 审核中” | `REVIEW_MODE=deterministic` |
| 采样漏掉问题 | 风险采样 + shadow 期全量对比 | `REVIEW_AGENT_SAMPLE_RATE=1.0` |
| 缓存过期/污染 | key 含 prompt/model/recipe/ruleset 版本；TTL 24h | 清空缓存或关闭缓存开关 |
| 模型端点故障 | 8s deadline + 确定性降级 + 熔断 | `REVIEW_USE_AGENT=false` |
| 输出被截断导致误判 | `truncated` 标记 + findings 上限；截断时降级为 warn | 提高 `MAX_PROMPT_CHARS` |

兼容策略：新增字段全部放在 `ReviewReport.stats` 与现有 JSON 列中，不新增数据库列；API 响应保持向后兼容。

## 8. 预期收益

| 指标 | 当前 | P0 后（预期） | P2 后（预期） |
|---|---|---|---|
| run 完成 p95（不含 OCR） | ~120s | ≤5s | ≤3s |
| AI 审核 p95 | 117s（同步） | ≤60s（异步） | ≤30s |
| 模型调用量 | 100% | ≤20% | ≤10% |
| Prompt tokens/文档 | 未设硬上限（受 64K 上下文约束） | ≤8K | ≤4K |
| 单文档 findings | 500+ | ≤30 | ≤20 |
| 确定性门禁 | 正常 | 不变 | 不变 |

## 9. 代码触点清单

- `services/review/service.py`：审核主流程与 Agent 任务构造（L51-L130）
- `services/review/config.py`：模式/采样/预算开关
- `services/review/api.py`：审核接口与异步状态查询
- `services/orchestration/workflow.py`：`_review_stage`、`_call_review`（L635-L700）
- `services/orchestration/models.py`：ReviewReport/Finding 持久化
- `services/agent/agents/review.py`：输入压缩、单次调用、输出解析（L59-L131）
- `services/agent/config.py`：context/output/timeout/tokenizer（L13-L27）
- `services/agent/model_gateway.py`：payload、max_tokens、并发控制（L326-L392）
- `services/agent/harness.py`：budget、usage、降级路径（L114-L160）
- `deploy/compose/docker-compose.yml`：`REVIEW_*`、`AGENT_*` 环境变量
- `web/src/components/review/ReviewFindings.tsx`、`web/src/pages/ExtractionPage.tsx`：AI 审核状态与发现展示

## 10. 建议的启动动作

1. 先将生产默认改为 `REVIEW_USE_AGENT=false`、`REVIEW_MODE=deterministic`，立即消除 96% 的审核延迟。
2. 按 P0.1–P0.3 完成异步审核与输入/输出瘦身，保持确定性门禁不变。
3. 用 `review_agent_bench.py` 在 60 份回归集上做 A/B，确认异步 p95 与 tokens 达标后再开启 `assist` 10% 灰度。
4. Shadow 期结束、precision 达标后，再考虑将 AI 审核纳入人工复核队列。
