# Agent 服务

M5 Qwen Agent Runtime：独立 `agent-service`，承载 RouterAgent、ReviewAgent、会话/检查点、上下文压缩、长任务分段与模型网关。

模型：`Qwen3.6-35B-A3B-NVFP4`（模型服务器 `192.168.1.35:9988`）。  
默认运行时：containerd + runc（M4 D-007）。

---

## 1. 目录

```text
services/agent/
├── api.py                 # /internal/agent:run、:resume、/health
├── config.py              # AGENT_* 配置
├── runtime.py             # 组件装配与角色分发
├── harness.py             # 工具循环、护栏、检查点/恢复
├── session.py             # SQLite 会话存储
├── model_gateway.py       # 三地址、10s 防抖切换、JSON 修复、usage
├── prompts.py             # prompt 版本与哈希
├── prompts/               # router.v1/review.v1/harness.v1
├── schema.py              # 输出 JSON Schema 校验
├── segmentation.py        # table/page/schema/token 分段与确定性合并
├── watchdog.py            # 模型服务器内存看门狗
├── context/
│   ├── tokenizer.py       # vLLM /tokenize（真实）+ 本地兜底
│   └── manager.py         # 预算、L1-L3 压缩、不变量
├── tools/
│   ├── registry.py        # 工具白名单、超时、结果截断
│   └── builtin.py         # 只读工具
└── agents/
    ├── router.py          # RouterAgent
    └── review.py          # ReviewAgent
```

执行契约：[packages/contracts/src/hanson_contracts/agent.py](../../packages/contracts/src/hanson_contracts/agent.py)。

---

## 2. API

### POST `/internal/agent:run`

```json
{
  "task_id": "task-1",
  "trace_id": "trace-1",
  "role": "router|review|repair|triage",
  "objective": "...",
  "inputs": {},
  "output_schema": {},
  "tools": ["get_table_summary"],
  "budget": {"max_steps": 24, "max_tool_calls": 32, "max_tokens": 64000, "wall_time_seconds": 300},
  "prompt_id": "router.v1"
}
```

返回 `AgentResult`：`status/output/usage/steps/session_id/prompt_id/prompt_hash/degraded/error_code`。

### POST `/internal/agent:resume`

```json
{"session_id": "...", "task": null, "additional_input": {}}
```

- 从 SQLite 会话恢复；失败/待人工会话可继续。
- 已完成/取消会话直接返回原结果。

### GET `/internal/agent/health`

返回模型地址、当前 active 端点、failover 窗口、模型列表、tokenizer 模式、会话库路径。

---

## 3. 角色

| 角色 | 实现 | 说明 |
|---|---|---|
| `router` | RouterAgent | 单次结构化调用；只能从 catalog 选配方；确定性 baseline 兜底 |
| `review` | ReviewAgent | 单次结构化调用；返回模型 Finding；review-service 负责规则链与合并 |
| `repair`/`triage` | AgentHarness | 通用工具循环，供 M6 使用 |

RouterAgent 护栏：

- 配方必须存在于 catalog；无效条目丢弃。
- 未覆盖的表用确定性结果补齐。
- 模型置信度 < 0.70 且与确定性结果冲突时，保留确定性结果并标注 `deterministic_guard`。
- 模型不可用/JSON 修复失败 → 返回确定性结果并 `degraded=true`。

ReviewAgent 护栏：

- Finding 必须引用已存在的 record_id/evidence_id。
- 与确定性 Finding 重复的条目会被去掉。
- 模型不可用 → 返回空模型 Finding，`degraded=true`，规则审核继续。

---

## 4. Model Gateway

- 端点：primary / secondary / tertiary，跳过空地址；默认 primary `http://39.107.239.208:35035`、secondary `http://192.168.188.75:9991`、tertiary `http://192.168.1.35:9988`。
- 启动探测：每个端点 GET `/v1/models`（2 秒超时），模型名必须等于 `AGENT_MODEL`；不可达/模型不匹配标记 down，active 落到第一个健康端点。
- 周期探测：每 60 秒复查；旧地址恢复且提供同一模型后自动启用/回切。
- 连接失败/429/5xx 视为可切换错误。
- **10 秒防抖**：首次失败只记录时间，不切换 active；连续失败满 10 秒才提交切换。
- 请求可在备地址立即完成，但 active 保持在主地址，短时抖动不回切。
- 切换后冷却 `AGENT_FAILOVER_COOLDOWN`（默认 30 秒）再探测主地址；主地址恢复且请求成功则回切。
- 4xx（非 429）不切换，直接返回请求错误。
- JSON：`chat_json` 解析失败时发送一次修复 prompt；仍失败返回 `ModelOutputInvalid`。
- usage：prompt/completion/total tokens 按调用累计到会话。

---

## 5. 上下文

- Tokenizer：优先 vLLM `POST /tokenize`（真实 tokenizer，根路径）；不可用时降级为 CJK/ASCII BPE 估算并标记 `degraded`。
- 预算：`AGENT_CONTEXT_WINDOW`（默认 64K，上限 128K）。
- 压缩：
  - L1（>70%）：丢弃最旧历史消息。
  - L2（>85%）：工具输出替换为摘要/artifact ref。
  - L3（>95%）：丢弃非不可变事实正文，保留 id/ref；仍超限则 `AGENT_CONTEXT_OVERFLOW`，不截断 JSON。
- 不变量：objective、schema、decisions、evidence IDs、header paths、units、字段集合必须保留；`ContextManager.check_lossless` 校验。

分段：

- `Segmenter.segment_tables`：按 header + 行 token 预算切分；保留 `row_start/row_end`。
- `segment_pages`：按行切 page；`segment_schema`：按 category 分组。
- `merge_segment_outputs`：按 key 确定性合并；冲突显式返回，不静默覆盖。

---

## 6. 工具与权限

| 工具 | 权限 | 说明 |
|---|---|---|
| `get_table_summary` | read | 表头、单位、5 行样例 |
| `get_records` | read | 记录，可按 table_id 过滤 |
| `get_evidence` | read | 证据行 |
| `get_recipe_catalog` | read | 配方目录 |
| `validate_record` | read | 确定性记录检查 |

- 任务 `tools` 是白名单；未列入 → `denied`。
- 单工具超时 10 秒；结果超过 4000 字符截断并标注 `truncated`。
- 相同工具+参数重复调用 → `AGENT_LOOP_DETECTED`。
- 所有内置工具只读；M5 不产生副作用，检查点可安全重放。

---

## 7. 会话与检查点

- SQLite：`AGENT_SESSION_DB`（默认 `/tmp/hanson-agent/sessions.db`）。
- 每步保存 `AgentSession`（steps/tool_calls/usage/context/checkpoint）。
- 恢复：`POST /internal/agent:resume`；失败会话会重置为 running 并从最后检查点继续。
- 单副本本地 SQLite；多副本部署需换 Postgres/Redis（见限制）。

---

## 8. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_MODEL` | `Qwen3.6-35B-A3B-NVFP4` | 模型名 |
| `AGENT_BASE_URL_PRIMARY/SECONDARY/TERTIARY` | `http://39.107.239.208:35035` / `http://192.168.188.75:9991` / `http://192.168.1.35:9988` | 三地址；启动探测自动跳过不可用/模型不匹配端点 |
| `AGENT_FAILOVER_SECONDS` | 10 | 连续失败切换窗口 |
| `AGENT_FAILOVER_COOLDOWN` | 30 | 回切探测冷却 |
| `AGENT_CONTEXT_WINDOW` | 65536 | 上下文预算 |
| `AGENT_MAX_OUTPUT_TOKENS` | 4096 | 单次输出上限 |
| `AGENT_TOKENIZER_MODE` | remote | `remote` / `heuristic` |
| `AGENT_SESSION_DB` | `/tmp/hanson-agent/sessions.db` | 会话库 |
| `AGENT_MAX_STEPS/MAX_TOOL_CALLS/WALL_TIME_SECONDS` | 24/32/300 | 护栏上限 |
| `AGENT_WATCHDOG_FLOOR_MB` | 4096 | 模型测试看门狗阈值（测试脚本使用） |

---

## 9. 看门狗

- `services/agent/watchdog.py`：`MemoryWatchdog`，可注入 clock/sleep，低于阈值触发 `WatchdogTripped`，可终止子进程。
- `scripts/dev/model-watchdog.py`：通过 SSH 读取模型服务器 `MemAvailable`；加载模式可终止刚启动的模型进程，测试模式只终止测试客户端。
- `scripts/dev/qwen-load-watchdog.sh`：模型服务器端加载守护；内存低于阈值终止加载进程，就绪后自动退出。
- 实测：加载 NVFP4 时 floor=8192 MiB，就绪后守护退出；测试 smoke/窗口基准使用 floor=4096 MiB。

---

## 10. 运行与测试

```bash
# Compose
cd deploy/compose && docker compose up -d agent review orchestration

# 健康
curl -s http://localhost:18003/internal/agent/health | python -m json.tool
curl -s http://localhost:18006/internal/review/rules | python -m json.tool

# 本地测试
python -m pytest tests/integration/agent -q

# 真实模型 smoke（带看门狗）
python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
  python scripts/dev/qwen-smoke.py

# 评测
python scripts/benchmark/review_eval.py
python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
  python scripts/benchmark/router_eval.py
python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
  python scripts/benchmark/window_benchmark.py
```

报告见：

- [M5 Agent 评测](../../docs/reports/M5-agent-eval.md)
- [M5 窗口基准](../../docs/reports/M5-window-benchmark.md)
- [M5 模型切换](../../docs/reports/M5-model-failover.md)
- [M5 看门狗](../../docs/reports/M5-watchdog.md)

---

## 11. 已知限制

1. RouterAgent/ReviewAgent 采用单次结构化调用；复杂多轮推理留给 M6 的 Repair/Triage。
2. ReviewAgent 只补充语义 Finding；业务规则仍以 review-service 为准。
3. 会话库为本地 SQLite，单副本；多副本需迁移到共享数据库。
4. `AGENT_BASE_URL_PRIMARY/SECONDARY` 已配置旧地址，但当前不可达/模型不匹配；启动/周期探测会标记 down 并自动使用 tertiary。真实三地址切换需旧地址服务同一模型。
5. Tokenizer 优先真实 `/tokenize`；模型服务不提供该接口时降级估算并标记 `degraded`。
