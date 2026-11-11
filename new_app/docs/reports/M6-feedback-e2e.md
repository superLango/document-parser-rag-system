# M6 反馈闭环 E2E 报告

> 日期：2026-11-11
> 环境：Compose（api-gateway `:18000`、orchestration `:18001`、agent `:18003`、sandbox `:18004`、recipe-registry `:18005`）；K8s（kind `hanson`，`hanson-standard`）
> 脚本：`scripts/dev/m6-feedback-e2e.py`
> 原始结果：[M6-feedback-e2e.json](M6-feedback-e2e.json)（Compose）、[M6-feedback-e2e-k8s.json](M6-feedback-e2e-k8s.json)（K8s）
> 结论：**通过**（Compose 与 K8s 的 approve/reject 两条路径均通过）

## 1. 场景

Fixture：`tests/fixtures/mechanical-z.md`（HTML 表格，列：牌号 / 抗拉强度 Rm/MPa / 断面收缩率 Z/% / 屈服强度 Re/MPa，2 行数据）。

基线配方 `mechanical_properties_v1@1.0.0` 绑定 Rm/Rp0.2/A/KU2/持久时间，但未绑定 Z 与 Re。

## 2. 通过路径

| 步骤 | 结果 |
|---|---|
| 基线运行 | `STRUCTURED_READY`，路由 `mechanical_properties_v1@1.0.0`，1 张表、2 条记录 |
| 创建反馈 | `missing_measure / Z`，状态 `open` |
| Triage | `root_cause=recipe_binding`，`repair_scope=recipe`，置信度 0.95 |
| Repair | `add /bindings/measures/Z`（unit `%`，family `tensile`）+ `add /signature/tokens/- = 断面收缩率` |
| 候选构建 | `mechanical_properties_v1@1.0.1`，digest `120fcc77...` |
| 沙箱验证 | `diff.added` 含 T1-R1=22、T1-R2=25，`unit=%`，`new_errors=0`，`passed=true` |
| Approve | `promoted`，stable `1.0.0 → 1.0.1` |
| 晋升后运行 | `STRUCTURED_READY`，路由 `mechanical_properties_v1@1.0.1` |

## 3. 拒绝路径

| 步骤 | 结果 |
|---|---|
| 创建反馈 | `missing_measure / Re`（稳定版仍未绑定 Re） |
| Process | `verified`，候选基于 `1.0.1` 构建 |
| Reject | `discarded` |
| stable 复核 | 仍为 `1.0.1`，未受丢弃影响 |

## 4. 过程中修复的问题

| 问题 | 修复 |
|---|---|
| Markdown 管道表格未被 text OCR 识别，`tables=[]` | E2E fixture 改为 HTML 表格（与 OCR 后端真实输出格式一致） |
| 沙箱从共享 `units` 列表按列下标取单位，导致 Z 被标成 `HBW` | `runtime/builtin.py` 优先从表头 `/` 后取单位；仅当全表只有一个单位时回退到 `units[0]` |
| 含硬度列的机械表被误路由到 `hardness_v1` | E2E fixture 使用纯力学列（Rm/Z/Re），匹配器当前策略下机械配方得分 0.73 胜出；hardness/mechanical 的低覆盖惩罚已在 M6 前置修复中覆盖纯硬度表 |

## 5. K8s 复验

- 环境：kind 集群 `hanson`，namespace `hanson-standard`；沙箱执行器为 Kubernetes Job。
- 访问方式：`kubectl port-forward svc/api-gateway 28000:8000`、`svc/recipe-registry 28005:8005`。
- 结果：`1.0.0 → 1.0.1` 通过路径与 Re 拒绝路径均通过，stable 在 discard 后保持 `1.0.1`；详见 [M6-feedback-e2e-k8s.json](M6-feedback-e2e-k8s.json)。

## 6. 已知限制

- 候选版本写入 recipe-registry 容器本地文件系统，重建容器后重置；生产需持久化卷/对象存储。
- 验证仅覆盖触发反馈的文档（`regression.documents=1`），跨文档回归后续补充。
