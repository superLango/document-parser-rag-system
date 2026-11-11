# M5 模型三地址切换报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 结论：10 秒防抖切换、短时抖动不切换、冷却后回切、全不可用降级均已验证。

---

## 1. 当前拓扑

| 端点 | 地址 | 状态 |
|---|---|---|
| primary | `http://39.107.239.208:35035` | 已配置（旧公网地址）；当前连接被关闭/不可用 → 探测标记 down |
| secondary | `http://192.168.188.75:9991` | 已配置（旧局域网地址）；当前超时 → 探测标记 down |
| tertiary | `http://192.168.1.35:9988` | 运行中，模型 `Qwen3.6-35B-A3B-NVFP4` |

M6 修复：primary/secondary 不再留空，而是填入旧代码记录地址；agent-service 启动时探测 `/v1/models`，并要求返回模型名与 `AGENT_MODEL` 一致。不可达或模型不匹配的端点标记 down，active 自动落到 tertiary；周期探测每 60 秒复查，旧地址恢复且提供同一模型时会自动回切。真实三地址切换需要旧地址服务同一模型。

---

## 2. 启动/周期探测

| 项 | 行为 |
|---|---|
| 启动探头 | 每个端点 GET `/v1/models`，超时 2 秒；模型名必须匹配 |
| 不可用标记 | `down_until = now + cooldown`，`last_error` 记录 HTTP/连接/模型不匹配 |
| active | 第一个 healthy 端点（primary→secondary→tertiary） |
| 周期探测 | 每 60 秒复查；失败端点保持 down，恢复端点重新可用 |
| 对请求影响 | 请求不再反复等待死地址；死地址仅在探测/冷却后重试 |

---

## 3. 切换策略

- 可切换错误：连接失败、超时、429、500/502/503/504；4xx（非 429）不切换。
- 连续失败窗口 `AGENT_FAILOVER_SECONDS=10`：首次失败只记录时间；满 10 秒才提交 active 切换。
- 请求可在备地址立即完成，但 active 保持主地址，短时抖动不回切。
- 切换后冷却 `AGENT_FAILOVER_COOLDOWN=30` 秒；冷却结束且主地址可用时优先探测主地址。
- 主地址成功 → 回切；备地址成功且主地址不可用 → 继续保持备地址。
- 全部失败 → `ModelUnavailable`，RouterAgent 降级确定性路由，ReviewAgent 返回空模型 Finding，review-service 继续规则审核。

---

## 4. 测试结果

测试：`tests/integration/agent/test_model_gateway.py`（httpx MockTransport，注入时钟）

| 场景 | 结果 |
|---|---|
| 启动探测：primary 模型不匹配、secondary 不可达、tertiary 正常 | active=tertiary；primary/secondary down |
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

## 5. 限制

1. primary/secondary 已配置旧地址，但当前不可达/模型不匹配；真实三地址故障切换需旧地址服务同一模型。
2. 切换窗口按“首次失败时间”计算，不是失败次数；这是刻意的 10 秒防抖语义。
3. 模型网关为进程内状态；多副本部署时各副本独立判断，生产可改为共享健康状态或网关层熔断。
4. 周期探测每 60 秒一次；旧地址恢复后最多 60 秒回切。

---

## 6. 结论

- primary/secondary 配置已补齐；启动探测避免死地址拖慢请求，当前自动使用 tertiary。
- 10 秒切换、防抖、回切、全不可用降级均符合 M5 验收。
- 旧地址恢复且提供 `Qwen3.6-35B-A3B-NVFP4` 后无需改代码，探测会自动启用。
