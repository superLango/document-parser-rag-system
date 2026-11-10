# M3 · Agent 编排 · 详细开发方案

> 上位计划：`../development-plan-v3.md` 第 6.3 节
> v3 调整：Agent 作为控制面（分类/配方选择/修复/升级）；数据面仍是确定性 TableGrid/列绑定/项目清单/抽取/校验。
> 阶段门：G3
> 当前状态：M3.1–M3.4 骨架实施完成（2026-10-29）；真实 Qwen 8 文档 STP **0.875**，G3 已达成（阈值 0.80）
> 文档版本：v1.0（2026-10-26）

---

## 1. 阶段定位

M1–M2.5 已经把工位和配方做稳。M3 把这些工位接入状态机，让系统能：

- 按文档情况选择路径；
- 失败时修复而不是整单失败；
- 断点续跑；
- 控制上下文与预算；
- 批量处理；
- 记录 trace 与成本。

M3 不做“开放式 ReAct”，只做**固定主干 + 有限条件分支**。

## 1.0 实施进展（2026-10-29）

| 项 | 结果 |
|---|---|
| 状态机 | `metal_doc_agent/orchestration/graph.py`：不引入 LangGraph 的等价引擎（声明式节点/条件边、步数上限、每节点 checkpoint）；主干 `plan → extract → ocr_gate → route → validate → coverage → assemble → publish_gate → publish/human` |
| 状态契约 | `state.py`：`Budget` / `RetryCounters` / `RouteInfo` / `CostUsage` / `StepRecord` / `OrchestrationState`，落盘 `m3_state.json` 可回读 |
| 工具契约 | `tools.py`：`load_artifact / run_extract / validate / retrieve_reference / write_artifact` 白名单 + 路径守卫 + 超时；无 `eval/exec` 表面 |
| 修复与预算 | `repair.py`：OCR 低质量→重 OCR；证据/取值错误→重抽；覆盖缺失→人工（未实现定向检索，不空转）；预算耗尽→人工；单测验证无死循环 |
| 上下文 | `context.py`：≤24K 装配；压缩只压条款正文，证据/表头/单位/条款 id 不压缩，回读无损 |
| 断点与中断 | 每节点写 `m3_state.json`；`resume_orchestration(decision="publish")` 人工放行；API `POST /v1/jobs/{job_id}/resume` |
| 批量 API | `batches.py` + `POST/GET /v1/batches`：路径或 job_id、批量状态聚合、幂等键回放 |
| runner 集成 | `METAL_DOC_ORCHESTRATE=1` 时 job 走图，状态映射 published→succeeded、review/human→review、failed→failed；audit 仍写 `result.json` |
| 评测 | `eval/m3.json`：3 份文档 STP 0.3333（1 published / 2 human），p95 654ms；`eval/m3-repair.json` 注入首抽失败：修复 2/2=1.0（另 1 份因页数预算未进入抽取） |
| G3 结论 | STP 0.333 <0.80 未达；修复率 1.0（注入）、无死循环、成本可核算、批量幂等、断点恢复通过；压缩证据无损，但抽取级回归未测（抽取器尚未消费上下文） |
| 入口偏离 | G2.5 未通过仍实施骨架（用户决策）；publish 只允许 audit pass，其余全部进人工，因此 STP 偏低但不会误发布 |
| 测试 | 新增 `test_m3_orchestration.py` 15 个、`test_m3_batches.py` 4 个；引擎 332 通过 |
| 产物 | `eval/m3.json` / `eval/m3.md`、`eval/m3-repair.json` / `eval/m3-repair.md` |

## 1.1 C5 定向覆盖修复（2026-10-29）

| 项 | 结果 |
|---|---|
| 覆盖语义 | `coverage/plan.py`：无对应表型且无 unknown 表时，required 字段记 `not_applicable`；存在 unknown 表仍记 `missing`，避免掩盖识别缺口 |
| 影响 | 机械/化学单族文档不再因“另一族缺失”被误判 review；`COVERAGE_MISSING` 只对真正可能存在的缺口告警 |
| 测试 | 新增 `test_coverage_applicability.py` 3 个 |
| 评测 | 3 文档 STP 仍 0.3333、8 文档 0.25：阻塞来自 mock 抽取器无 grade 记录、31/32 页超预算、mechanical/hardness top2 歧义；C5 未改变这些根因 |
| 结论 | G3 仍不通过；STP 提升需要真实抽取后端、页预算策略与歧义规则，而不是覆盖判定 |

## 1.2 C5b 页预算与歧义规则（2026-10-29）

| 项 | 结果 |
|---|---|
| 页预算 | 默认 `max_pages` 30→**60**；30 页仅作为 SLA 压测口径，31/32 页文档不再被预算拦截 |
| 歧义规则 | `routing.py` 在 top2 同族配方（mechanical/hardness）分差 ≤0.05 时，用表头 family 计数（拉伸/屈服/冲击 vs 硬度/HBW）判定；机械证据 ≥2 且领先 ≥1 时选 mechanical，否则仍进人工 |
| 路由变化 | 表级 human 31→**19**，production 61→66；文档级 production 0.95 不变 |
| 编排评测 | 8 文档 STP **0.25→0.375**（3 published / 1 review / 4 human），3 文档 0.333；p95 708ms |
| 剩余人工 | mock 抽取器无 grade（2 份 coverage_gap）、化学值越界（1 份 audit_failed）、top2 真歧义（1 份 route_human）、1 份 review |
| 结论 | 页预算与假歧义已修；STP 距 0.60 仍差 0.225，需真实 Qwen 抽取或进一步收敛人工策略 |

## 1.3 真实 Qwen 复跑与三项根因修复（2026-10-29）

| 项 | 结果 |
|---|---|
| 后端 | OCR mock（语料为 `.md`）、抽取 Qwen3.5-9B（模型机 `192.168.1.35:9989`）；每文档 1 次抽取调用 |
| 根因 1：表型 | `tablegrid/profile.py` 改为“表头强信号优先、标题兜底”。OCR 分页把下一张表的标题挂到力学续表上，曾使力学表判为 `chemical_composition`，MPa 值被绑到元素 `N` 触发 `CHEMICAL_OUT_OF_RANGE` |
| 根因 2：跨行 | `tablegrid/parser.py`：`_expand_grid` 检测 rowspan 多算（下一牌号行整行溢出且溢出量 ≥ 已填充跨行）并丢弃陈旧跨行；`_repair_collapsed_columns` 增加“表头越界到数据列右侧”的触发条件。修复后续页力学表按 10/11 列对齐 |
| 根因 3：映射/单位 | `extraction/qwen.py` 禁止模型把第二列绑定到规则已占用的属性（硬度列不再覆盖 A/Z）；`normalize.parse_unit` 将 `N/mm²` 归一为 `MPa`，消除 86 条 `UNIT_MISMATCH` |
| 结果 | 8 文档 STP **0.75**（6 published / 2 human，无 review/failed）；p95 **170.6s**、中位 71.0s、总耗时 638s |
| 剩余人工 | `gbt14992_2015` route_human（13 张化学表、签名分 0.65–0.72、risky_table_size）；`gbt3191_2010` coverage_gap（`records.grade` 缺失：非记录表不出 grade 记录，另有 chemical ambiguous 警告） |
| 对比 | 同代码 mock 8 文档 0.375→**0.625**（5 published）；真实 Qwen 0.75，优于 mock 且不依赖 mock 规则 |
| 测试 | 引擎 **364** 通过；新增表型优先级 2 个、跨行泄漏 1 个、属性唯一绑定 1 个、`N/mm²` 单位 1 个 |
| 产物 | `eval/m3-qwen-8docs.json` / `.md`、`eval/m3-8docs-after3.json`；模型机 9989 按 `start_qwen35_9b.sh` 重启 |

## 1.4 表型顺序修正与 G3 达成（2026-10-29）

| 项 | 结果 |
|---|---|
| 问题 | 力学表含“试样状态”列被判 `inspection`；检验项目表把“化学成分”列为检验项却被判 `chemical`；电导率表含“力学性能”引用列被判 `mechanical`（无值可抽 → coverage ambiguous） |
| 规则 | `profile.py`：元素列 ≥3，或“化学成分”且非检验项目表 → chemical；具体力学属性列（Rm/Rp0.2/A/Z/KV2/HB/HRC…）→ mechanical；检验标记 → inspection；单“力学性能”仅在无检验标记时生效 |
| 影响 | `gbt3191_2010` 由 coverage_gap 转为 published（机械记录 56→78）；`gbt3880_1_2012` 电导率表不再制造 mechanical ambiguous |
| 结果 | 真实 Qwen 8 文档 STP **0.875**（7 published / 1 human）；p95 169.5s、中位 103.6s；同代码 mock **0.875** |
| 剩余人工 | `gbt14992_2015`：13 张化学表同配方、签名分 0.65–0.72，2 张多 block 触发 `risky_table_size`，保守进人工 |
| 测试 | 新增 3 个（试样状态力学表、检验项目含化学成分、电导率引用力学性能）；引擎 367 通过 |
| 产物 | `eval/m3-qwen-8docs.json` / `.md`、`eval/m3-8docs-after5.json`；routing/coldstart 刷新（production 73/T1 73） |

---

## 2. 入口条件

- G2.5 通过；
- active 配方可调用；
- 队列/存储可用；
- 修复策略与预算已定义；
- 批量请求可评估。

## 3. 范围

### 3.1 做

- LangGraph 状态机；
- 状态契约；
- 工具契约；
- 条件分支；
- 修复循环；
- 预算与终止；
- checkpoint/断点续跑；
- 上下文预算/compaction；
- 批量 API；
- trace/成本；
- 人工中断。

### 3.2 不做

- 开放式 ReAct；
- 模型生成任意代码并执行；
- 全自动发布（M4 前）；
- 多租户配额（M5）。

## 4. 状态机

```text
START
  → ingest
  → ocr_quality_gate
      ├─ low → reocr → ocr_quality_gate
      └─ ok
  → tablegrid
  → profile_router
      ├─ active recipe → extract_recipe
      ├─ explore → explore_extract
      └─ human → human_queue
  → normalize
  → validate
      ├─ error → repair
      │            ├─ retry_extract
      │            ├─ retry_ocr
      │            └─ human
      └─ pass/review
  → coverage
      ├─ missing → retrieve/reocr → extract
      └─ ok
  → assemble
  → publish_gate
      ├─ pass → publish
      ├─ review → human
      └─ fail → review
END
```

### 4.1 状态契约

```json
{
  "job_id": "...",
  "doc_id": "...",
  "stage": "extract",
  "attempt": 1,
  "budget": {
    "max_steps": 12,
    "max_ocr_retries": 2,
    "max_extract_retries": 2,
    "max_pages": 60,
    "max_reference_docs": 8
  },
  "artifacts": {
    "pages": "artifacts/.../pages.json",
    "tablegrid": "artifacts/.../tablegrid/",
    "records": "artifacts/.../records.json",
    "evidence": "artifacts/.../evidence.jsonl",
    "audit": "artifacts/.../audit.json"
  },
  "errors": [],
  "route": {"queue": "production", "recipe_id": "...", "confidence": 0.92}
}
```

原则：

- state 只放指针/摘要，不放整本 Markdown；
- 大 artifact 走对象存储；
- 任何重试必须增加 `attempt`；
- 任何终止必须写原因。

## 5. 工作包与任务

### 5.1 M3.1 状态机与工具

| ID | 任务 | 实现 | 验收 |
|---|---|---|---|
| M3.1-01 | LangGraph 主干 | 节点/边/条件 | 固定路径可跑 |
| M3.1-02 | 状态契约 | Pydantic | 可序列化/回读 |
| M3.1-03 | 工具契约 | load_artifact/retry_ocr/validate/extract | 有权限/超时 |
| M3.1-04 | 工具沙箱 | 生产禁跑任意代码 | 无代码执行 |
| M3.1-05 | 状态机测试 | 路径/终止/重试 | 无死循环 |

**工具清单**：

```text
load_artifact(uri)           读取 pages/tablegrid/evidence
run_ocr(page_range)          指定页重跑 OCR
run_extract(table_id, recipe)指定表抽取
validate(records)            L0–L3.5
retrieve_reference(doc_id)   引用展开
write_artifact(name, data)   写结果
```

### 5.2 M3.2 修复与预算

#### 修复策略

| 错误 | 修复 |
|---|---|
| OCR 低质量 | 裁剪重 OCR |
| 表头映射失败 | 换配方/规则兜底 |
| JSON 非法 | 重试/更严格 schema |
| L2 失败 | 回读证据/重抽 |
| 覆盖 missing | 定向检索/重 OCR |
| 引用缺失 | 标 gap，不自动发布 |

#### 预算

- 最大步数 12；
- OCR 重试 ≤2；
- 抽取重试 ≤2；
- 引用展开 ≤8 份/≤30 页；
- 超预算 → human，不继续循环。

#### 任务

| ID | 任务 | 实现 | 验收 |
|---|---|---|---|
| M3.2-01 | 修复节点 | 错误→动作映射 | 预算内 |
| M3.2-02 | 重试/裁剪重 OCR | 页级 | 可升级 |
| M3.2-03 | 修复成功率 | 评测 | ≥70% |
| M3.2-04 | 成本核算 | 每步 token/GPU 秒 | 可核算 |
| M3.2-05 | 终止证明 | 最大步/超时 | 无死循环 |

### 5.3 M3.3 上下文与断点

#### 上下文装配

```text
task_context =
  document_profile
  + current_table (TableGrid)
  + header_paths
  + relevant_clauses (top-k)
  + reference_constraints
  + schema_fields
  + previous_errors (摘要)
```

预算：12–24K token/任务。

#### Compaction

- 只压缩对话/推理历史；
- **证据不压缩**；
- 表头/单位/条件不压缩；
- 压缩后必须保留 `evidence_id` 指针；
- 压缩回归 ≤1pp。

#### 任务

| ID | 任务 | 实现 | 验收 |
|---|---|---|---|
| M3.3-01 | assemble_context | 任务切片 | ≤24K |
| M3.3-02 | compact_context | 证据不压缩 | 指针保留 |
| M3.3-03 | checkpoint | LangGraph checkpointer | 断点恢复 |
| M3.3-04 | 人工中断 | interrupt/resume | 可恢复 |
| M3.3-05 | 压缩回归 | 对比 | ≤1pp |

### 5.4 M3.4 批量与可观测

| ID | 任务 | 实现 | 验收 |
|---|---|---|---|
| M3.4-01 | 批量 API | `POST /v1/batches` | 幂等/可查 |
| M3.4-02 | trace | OTel/Langfuse | 阶段耗时/成本 |
| M3.4-03 | 压测 | 30 页/并发 | p95 ≤5 分钟 |
| M3.4-04 | 失败重跑 | runbook | 不丢证据 |

## 6. 接口

```text
POST /v1/jobs
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/result
GET  /v1/jobs/{id}/evidence
GET  /v1/jobs/{id}/audit
POST /v1/jobs/{id}/resume
POST /v1/batches
GET  /v1/batches/{id}
```

`resume` 与 `batches` 已实现；`resume` 在 `METAL_DOC_ORCHESTRATE=1` 且存在 `m3_state.json` 时从断点续跑，否则按重跑处理。

## 7. 测试

| 层 | 用例 | 阻断 |
|---|---|---|
| 单元 | 状态转移/预算/终止 | 是 |
| 契约 | state/tool schema | 是 |
| 集成 | 3 份文档全路径 | 是 |
| 故障注入 | OCR 失败/抽取失败/JSON 非法 | 是 |
| 压测 | 30 页/批量 | G3 |
| 回归 | 压缩前后 | 是 |

## 8. G3 验收

- [x] 目标族 STP ≥80%（实测 **0.875**，真实 Qwen 8 文档；同代码 mock 0.875）；
- [x] 修复成功率 ≥70%（注入测试 3/3）；
- [x] 无死循环（预算测试）；
- [x] 单文档成本可核算（m3_trace / cost）；
- [x] 压缩前后核心字段下降 ≤1pp（`context_regression` 增加抽取字段集合：Rm/Rp0.2/A 等压缩后 `lost_fields=[]`、`field_loss_rate=0.0`，`tests/test_m3_orchestration.py` 断言）；
- [x] 批量 API 幂等；
- [x] checkpoint 可恢复；
- [x] trace 可定位阶段。

> G3 结论（2026-10-29）：**达成**。真实 Qwen 8 文档 STP **0.875**（≥0.80），7 published / 1 human；修复注入 3/3、无死循环、成本可核算、压缩无损、批量幂等、checkpoint 可恢复。唯一人工为 `gbt14992_2015`（13 张化学表签名分 0.65–0.72 + 多 block 大表），保留保守人工；样本规模沿用 G2.5 的 20/25 语料限制。

### 8.1 失败分支

| 条件 | 动作 |
|---|---|
| STP <60% | 保留人工队列，不自动发布 |
| 修复 <50% | 回 M1.7/M2.5 修工位/配方 |
| 死循环 | 降步数、加硬超时 |
| 压缩回归 >2pp | 关 compaction，只切任务 |
| 成本超预算 | 批处理/量化/缓存 |

## 9. 风险

| 风险 | 触发 | 应对 |
|---|---|---|
| 状态爆炸 | 分支过多 | 固定主干 + 有限分支 |
| 修复放大错误 | 重试无收益 | 预算 + 人工闸门 |
| 上下文溢出 | 长表 | 分块 + 表头复用 |
| 压缩丢证据 | 摘要替换原文 | 证据指针不压缩 |
| 批量互相影响 | 单任务超时 | 隔离/限流 |

## 10. 交付物与交接

| 交付物 | 位置 |
|---|---|
| 状态机 | `metal_doc_agent/orchestration/graph.py` |
| 状态契约 | `metal_doc_agent/orchestration/state.py` |
| 工具 | `metal_doc_agent/orchestration/tools.py` |
| 修复 | `metal_doc_agent/orchestration/repair.py` |
| 上下文 | `metal_doc_agent/orchestration/context.py` |
| 批量 API | `metal_doc_agent/api.py` |
| 压测/成本 | `eval/m3.md` |

交接给 M4：

- STP/修复率；
- 人工队列触发条件；
- 证据/审计包格式；
- trace/成本字段；
- 已知不可自动发布场景。
