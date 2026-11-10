# SLO 与容量（M5.1-04 / M5.2-04）

## 1. SLI / SLO

| 服务 | SLI | SLO | 测量 |
|---|---|---|---|
| 平台 API | 非 5xx 请求占比 | ≥99.5%/月 | Ingress/应用指标 |
| 引擎 API | `/ready` 成功占比 | ≥99.5%/月 | Prometheus `up` + 探针 |
| 单文档处理 | p95 端到端（30 页） | ≤5 分钟 | trace/离线评测 |
| 任务可靠性 | 失败率 | <2% | `engine_jobs{status="failed"}` |
| 结果质量 | 证据率 | ≥95% | `eval/m4.json` / 抽样 |
| 结果质量 | silent error | 0（抽样） | `eval/m4.md` |
| 复核吞吐 | 复核积压 | ≤1 个工作日 | `platform_documents{status="review"}` |

## 2. 错误预算

- 月度可用性预算 0.5%：耗尽后冻结非紧急发布，仅允许回滚/修复；
- 延迟预算连续 3 天超 SLO → 扩池或限流；
- 质量 SLO 破线 → 暂停自动发布，转人工复核（沿用 M3/M4 闸门）。

## 3. 容量基线

| 资源 | 基线 | 扩容信号 |
|---|---|---|
| engine-api | 2 副本 × 0.25C/512Mi | CPU >70% 10 分钟 |
| platform-api | 2 副本 × 0.25C/512Mi | CPU >70% 10 分钟 |
| worker-prod | 2 副本 × 0.5C/1Gi | queued >20 持续 10 分钟（手动扩） |
| worker-explore | 1 副本 × 0.25C/512Mi | explore backlog >50 |
| 模型平面 | 1.35 单机 GPU | 队列等待 / OOM |

## 4. 成本

- 以“每页资源单位”核算：OCR 页数、抽取调用次数、端到端 GPU/CPU 秒；
- 单价由业务确认后填入 `infra/cost_model.json`；
- `python -m tools.cost_report` 产出每页资源与成本估算，供月度复盘。

## 5. 当前测量缺口

- `tools/sla_probe.py` 可从任务存储计算可用性/失败率/p95，但当前仅 14 个本地任务（`insufficient_data`），需试点流量（≥200 完成任务）；
- 模型 token 已逐任务记账（`trace.json.model_usage` → `JobState.summary.model_tokens` / `metrics.json`），旧 run 未回填；
- 试点部门未确认 SLA 赔付条款（窗口、口径、赔付方式）。
