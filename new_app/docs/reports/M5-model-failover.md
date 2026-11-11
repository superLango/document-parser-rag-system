# M5 模型三地址切换报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 结论：10 秒防抖切换、短时抖动不切换、冷却后回切、全不可用降级均已验证。

---

## 1. 当前拓扑

| 端点 | 地址 | 状态 |
|---|---|---|
| primary | 空 | 未配置 |
| secondary | 空 | 未配置 |
| tertiary | `http://192.168.1.35:9988` | 运行中，模型 `Qwen3.6-35B-A3B-NVFP4` |

生产应补齐 primary/secondary；当前 Compose/K8s 只配置 tertiary，切换逻辑由三地址单元测试覆盖。

---

## 2. 切换策略

- 可切换错误：连接失败、超时、429、500/502/503/504；4xx（非 429）不切换。
- 连续失败窗口 `AGENT_FAILOVER_SECONDS=10`：首次失败只记录时间；满 10 秒才提交 active 切换。
- 请求可在备地址立即完成，但 active 保持主地址，短时抖动不回切。
- 切换后冷却 `AGENT_FAILOVER_COOLDOWN=30` 秒；冷却结束且主地址可用时优先探测主地址。
- 主地址成功 → 回切；备地址成功且主地址不可用 → 继续保持备地址。
- 全部失败 → `ModelUnavailable`，RouterAgent 降级确定性路由，ReviewAgent 返回空模型 Finding，review-service 继续规则审核。

---

## 3. 测试结果

测试：`tests/integration/agent/test_model_gateway.py`（httpx MockTransport，注入时钟）

| 场景 | 结果 |
|---|---|
| 主地址连接失败，备地址成功 | 请求成功；primary 标记不可用；active 仍为 primary（10 s 防抖） |
| 连续失败至 11 s | 提交切换；active=secondary |
| 主地址恢复 + 冷却 30 s | 回切 primary；active=primary |
| 三地址全部失败 | `ModelUnavailable` |
| 非法 JSON | 修复一次成功；修复失败 `ModelOutputInvalid` |
| usage | prompt/completion/total 正确累计 |

真实模型：

```text
GET http://192.168.1.35:9988/v1/models
→ ["Qwen3.6-35B-A3B-NVFP4"]

qwen-smoke.py（带看门狗）
→ {"ok": true}, 40 prompt / 13 completion tokens, 1505 ms
```

---

## 4. 限制

1. primary/secondary 当前为空，三地址实测需补齐地址或在测试环境启动两个假模型服务。
2. 切换窗口按“首次失败时间”计算，不是失败次数；这是刻意的 10 秒防抖语义。
3. 模型网关为进程内状态；多副本部署时各副本独立判断，生产可改为共享健康状态或网关层熔断。

---

## 5. 结论

- 10 秒切换、防抖、回切、全不可用降级均符合 M5 验收。
- 当前单 tertiary 生产可用；补齐 primary/secondary 后无需改代码，只改 `AGENT_BASE_URL_*`。
