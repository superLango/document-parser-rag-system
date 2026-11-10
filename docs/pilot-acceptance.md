# 试点验收（G5）

> 状态：**未完成**。本文件是验收模板与证据索引，签字栏为空；未签字前不得对外承诺 SLA。

## 1. 验收范围

- 参与部门：待定（建议 1 个标准归口部门 + 1 个使用部门）
- 文档量：100–300 份真实标准（覆盖 5 个标准族）
- 周期：4 周（第 1 周灰度 10%，第 2–3 周全量，第 4 周复盘）

## 2. 验收标准

| 项 | 目标 | 证据 |
|---|---|---|
| 处理成功率 | ≥99%（失败可重跑） | `engine_jobs` / 任务中心 |
| p95 30 页 | ≤5 分钟 | [eval/loadtest.md](../metal-doc-agent/eval/loadtest.md)、生产监控 |
| 证据率 | ≥95% | [eval/m5.md](../metal-doc-agent/eval/m5.md) |
| silent error | 0（抽样） | [eval/m4.md](../metal-doc-agent/eval/m4.md) |
| 复核一次通过率 | ≥80% | [eval/m4.md](../metal-doc-agent/eval/m4.md) + 生产复核事件 |
| 高风险拦截 | 100% | 字段复核确认闸门 |
| 成本/页 | 业务确认单价后达标 | [eval/m5-cost.md](../metal-doc-agent/eval/m5-cost.md) |
| 安全 | 无高危 | [security.md](security.md) |
| 备份恢复 | 演练通过 | [infra/backup/drill.md](../infra/backup/drill.md) |

## 3. 证据包

- 就绪/质量/延迟：[eval/m5.md](../metal-doc-agent/eval/m5.md)
- 压测：[eval/loadtest.md](../metal-doc-agent/eval/loadtest.md)
- 成本：[eval/m5-cost.md](../metal-doc-agent/eval/m5-cost.md)
- 备份演练：[eval/backup-drill.md](../metal-doc-agent/eval/backup-drill.md)
- 安全扫描：[eval/security-scan.json](../metal-doc-agent/eval/security-scan.json)
- 汇总检查表：`python -m tools.pilot_pack` → [eval/pilot-pack.md](../metal-doc-agent/eval/pilot-pack.md)

## 4. 当前阻塞

| 项 | 状态 | 已准备 | 待外部输入 |
|---|---|---|---|
| E1 生产 SLA | 未测 | `tools/sla_probe.py` → [eval/sla.md](../metal-doc-agent/eval/sla.md)（当前 insufficient_data，14 jobs） | 试点流量（≥200 完成任务）与 SLA 条款 |
| E2 Postgres/K8s 恢复 | 未演练 | 加密备份/恢复脚本、`infra/backup/postgres_drill.sh`、本地加密演练 PASS | 试点 K8s/Postgres 环境与备份介质 |
| E3 外部安全评审 | 未排期 | [security-review-package.md](security-review-package.md)、密钥扫描 0 findings | 评审方与排期 |
| E4 成本单价 | 未确认 | `infra/cost_model.json` 增加 `pending_fields/confirmed_by`，`token_per_1k` 位就绪 | 业务确认 4 个单价 |
| E5 试点/值班 | 未签字 | [pilot-acceptance.md](pilot-acceptance.md) 签字栏、[oncall.md](oncall.md) 排班表与升级路径 | 试点部门、值班名单、签字 |

补充：

1. 备份已加密并完成本地加密/解密/篡改检测演练，但整环境恢复仍待 E2；
2. 成本只能输出资源单位（页/token/调用/CPU 秒），金额需 E4 单价后计算；
3. 未完成签字前，不对外承诺 SLA。

## 5. 签字

| 角色 | 姓名 | 日期 | 结论 |
|---|---|---|---|
| 业务负责人 |  |  | 待签 |
| 技术负责人 |  |  | 待签 |
| 安全负责人 |  |  | 待签 |
| 运维负责人 |  |  | 待签 |
