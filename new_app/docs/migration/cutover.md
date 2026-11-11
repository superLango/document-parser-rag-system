# M8 灰度与切换方案

> 日期：2026-11-12
> 环境：本地 WSL Compose + kind（验证）；生产按 Ingress/DNS 等价执行
> 关联：[回滚手册](../runbooks/rollback.md)、[归档清单](archive.md)、[切换演练报告](../reports/M8-cutover-drill.json)

## 1. 双入口架构

```text
用户
  → 统一入口（Nginx / Ingress，本地 18088）
      ├─ 新系统：web 4173（生产为静态站点） + api 18000（/v1）
      └─ 旧系统：web 8080 + api 8000（/health）
```

- 旧系统代码与数据不改动，保持可服务。
- 新系统使用独立数据库/对象存储；词典已导入（2203 条）。
- 切换只改入口 upstream，不迁移数据、不双写。

## 2. 灰度步骤

| 步骤 | 范围 | 观察项 | 退出条件 |
|---|---|---|---|
| 0 | 试点文档 10 份 | 解析成功、记录数、审核结论 | 失败 ≤1 |
| 1 | 内部用户 | 上传/解析/反馈闭环 | 无阻断缺陷 |
| 2 | 10% 流量 | 错误率、p95、5xx | 24h 错误率 ≤1% |
| 3 | 50% 流量 | 同上 + 数据一致性 | 24h 错误率 ≤1% |
| 4 | 100% 流量 | 全量指标 | 24h 无 P0 |
| 5 | 旧系统只读 | 访问量、回滚通道 | 一个发布周期后归档 |

本地等价演练：用 Nginx 统一入口在“新/旧” upstream 间切换，验证切换与回切耗时；不模拟真实流量比例。

## 3. 切换前检查

- [ ] `GET /v1/health` 新网关 200；`GET /health` 旧 API 200。
- [ ] 词典版本与旧系统一致：`hanson-ht-64c316a7`。
- [ ] 最近 10 份试点文档解析成功，结果可查询。
- [ ] 反馈闭环通过/拒绝路径可用（M6 E2E）。
- [ ] 压测错误率 ≤1%（M8 压测 0%）。
- [ ] 回滚入口可用（Nginx/Ingress 可改 upstream）。
- [ ] 监控：5xx、p95、队列、沙箱失败率。

## 4. 切换操作（本地演练命令）

```bash
# 启动统一入口（新系统 upstream）
bash new_app/scripts/dev/m8-cutover-drill.sh

# 手工切换：把 old.conf 覆盖 active.conf 后 reload
docker cp old.conf hanson-cutover-entry:/etc/nginx/conf.d/default.conf
docker exec hanson-cutover-entry nginx -s reload

# 回切：把 new.conf 覆盖后 reload
docker cp new.conf hanson-cutover-entry:/etc/nginx/conf.d/default.conf
docker exec hanson-cutover-entry nginx -s reload
```

验证：

```bash
curl -s http://localhost:18088/v1/health     # 新
curl -s http://localhost:18088/health        # 旧
curl -s -o /dev/null -w '%{http_code}' http://localhost:18088/
```

## 5. 演练结果（2026-11-12）

| 项 | 结果 |
|---|---|
| 新入口 `/v1/health` | `api-gateway` 200 |
| 切到旧系统 | 成功，**455 ms** |
| 旧 Web | 200 |
| 回切新系统 | 成功，**475 ms** |
| 报告 | [M8-cutover-drill.json](../reports/M8-cutover-drill.json) |

均远低于 5 分钟回滚门槛。

## 6. 回滚触发条件

- 5 分钟内错误率 > 5%。
- p95 超过基线 2 倍。
- 数据不一致/丢失。
- 阻断性缺陷（无法上传/解析/查看结果）。
- 词典/配方版本异常导致大面积错误。

## 7. 监控与观察

| 指标 | 来源 | 阈值 |
|---|---|---|
| HTTP 5xx | api-gateway 日志/网关 | ≤1% |
| 解析失败率 | `runs.status=FAILED` | ≤1% |
| p95 运行耗时 | `runs` 时间戳 | ≤120s（单文档） |
| 沙箱失败 | run_stages/sandbox | ≤1% |
| Agent 失败 | agent 日志 | ≤1% |
| 反馈积压 | feedback status=open | 观察 |

## 8. 责任与沟通

| 角色 | 职责 |
|---|---|
| 项目负责人 | 执行切换/回滚、观察指标、决策 |
| 业务（按需） | 试点文档确认、结果抽查 |
| DevOps（兼） | Ingress/DNS、监控、证书 |

切换窗口选择业务低峰；切换前 30 分钟通知，回滚后 10 分钟内通报。
