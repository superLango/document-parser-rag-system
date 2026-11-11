# 反馈、修复与晋升运维手册

> 适用版本：M6（2026-11-11）
> 相关 API：api-gateway `/v1/feedback`、orchestration `/internal/feedback`、recipe-registry `/internal/recipes`

## 1. 闭环概览

```text
POST /v1/feedback
  → POST /v1/feedback/{id}/process
       TriageAgent → RepairAgent → 构建 candidate 配方 → 沙箱定向重解析
  → GET  /v1/feedback/{id}/verification
  → POST /v1/feedback/{id}/verify {decision: approve|reject}
       approve → stable 通道切换，写 promotions + run_events
       reject  → 清除 candidate 指针，stable 不变
```

状态：`open → processing → verified → promoted | discarded`；失败或需人工时停在 `needs_more_info`，可修复后重新 `process`。

## 2. 创建与处理

```bash
curl -s -X POST http://localhost:18000/v1/feedback \
  -H 'Content-Type: application/json' -d '{
    "run_id": "<run-id>",
    "category": "missing_measure",
    "target": {"recipe_id": "mechanical_properties_v1", "measure": "Z", "unit": "%", "family": "tensile"},
    "description": "断面收缩率 Z 未抽取",
    "expected_value": "22",
    "reporter": "operator"
  }'

curl -s -X POST http://localhost:18000/v1/feedback/<feedback-id>/process
curl -s http://localhost:18000/v1/feedback/<feedback-id>/verification
```

去重键：`sha256(run_id | category | target | description | expected_value)`。同一 run 的同一问题重复提交会返回已有反馈；如需新开一条（例如拒绝路径演练），必须改变 description/category/expected_value。

## 3. 验证与决策

```bash
curl -s -X POST http://localhost:18000/v1/feedback/<feedback-id>/verify \
  -H 'Content-Type: application/json' \
  -d '{"decision": "approve", "reason": "reviewed", "actor": "operator"}'
```

- `approve` 前置条件：状态 `verified` 且 `verification.passed=true`。
- `reject` 对状态无前置要求（只要已有 candidate），执行 discard，stable 不变。
- `actor` 必填，写入 `promotions` 与 `run_events`。

VerificationPackage 关键字段：

| 字段 | 含义 |
|---|---|
| `diff.added` | 候选版本新增的目标字段（记录级） |
| `diff.changed` | 目标字段值发生变化 |
| `diff.removed` | 目标字段消失（会阻止通过） |
| `regression.new_errors` | 候选运行新增的 error 级诊断 |
| `passed` | `目标存在新增/变化 && 无 removed && new_errors=0` |
| `artifacts` | 候选沙箱产物（result/records/evidence/diagnostics/metrics/manifest） |

## 4. 常见 `needs_more_info` 原因

| 消息/代码 | 处理 |
|---|---|
| `Triage requires human review.` | 补充反馈证据（期望值、原文引用）后重新 `process` |
| `Repair proposal needs human handling.` | 修复范围不是 recipe（模板/引擎/数据），转人工或拆分为新里程碑 |
| `TRIAGE_INVALID` / `REPAIR_INVALID` | Agent 输出不符合契约；检查 agent 日志与模型健康 |
| `AGENT_UNAVAILABLE` / `AGENT_FAILED` | Agent 服务或模型不可达；见第 6 节 |
| `REGISTRY_UNAVAILABLE` / `REGISTRY_ERROR` | 配方注册中心不可达或补丁被拒；检查 registry 日志 |
| `Verification failed: Target X: not fixed` | 候选配方未绑定目标列，或 OCR 未识别目标列 |
| `candidate sandbox failed` | 沙箱失败；查看 `error_code` 与沙箱日志 |

重新处理：状态为 `open`/`needs_more_info` 时可直接再次 `POST /process`。

## 5. 回滚与审计

```bash
# 回滚 stable 到上一版本
curl -s -X POST http://localhost:18005/internal/recipes/mechanical_properties_v1/rollback \
  -H 'Content-Type: application/json' -d '{"channel":"stable","actor":"operator","note":"rollback"}'

# 查看通道指针
curl -s http://localhost:18005/internal/recipes/mechanical_properties_v1
```

- 审计表 `promotions`：`feedback_id / recipe_id / from_version / to_version / channel / action / actor / note`。
- 运行事件：`run_events` 中 `feedback.promoted`、`feedback.discarded`。
- 配方 registry history：`data/recipes/registry.json` 的 `history` 数组。

## 6. 故障排查

1. **Agent 不可用**：`GET http://localhost:18003/healthz`；检查 `AGENT_BASE_URL_*` 与模型端点；启动探测失败会自动降级到备用地址。
2. **Registry 不可用**：`GET http://localhost:18005/healthz`；候选包写入 registry 容器本地文件系统。
3. **沙箱验证失败**：查看 VerificationPackage `artifacts` 中的 `diagnostics.json`；确认候选 manifest 可通过 registry 访问（沙箱通过 `RECIPE_REGISTRY_URL` 拉取）。
4. **晋升后新运行仍用旧版本**：确认运行 `recipe_channel=stable`，并检查 routing 产物中的 `recipe_id/version`。

## 7. 已知限制

- **候选/晋升数据未持久化**：registry 数据目录位于容器文件系统，`docker compose up --force-recreate` 会重置为镜像内初始版本。生产环境必须挂载持久卷或对象存储。
- **验证范围**：当前仅对触发反馈的文档做定向重解析，`regression.documents=1`；跨文档回归在后续里程碑补充。
- **审批模型**：`actor` 为字符串标识，未接入 RBAC（M7 之后）。

## 8. E2E 演练

```bash
# Compose 栈运行中
python scripts/dev/m6-feedback-e2e.py
```

脚本覆盖：上传 fixture → 基线运行 → 创建 Z 反馈 → process → verified → approve → 新运行使用新 stable → 创建 Re 反馈 → process → reject → discard 且 stable 不变。结果写入 `docs/reports/M6-feedback-e2e.json`。
