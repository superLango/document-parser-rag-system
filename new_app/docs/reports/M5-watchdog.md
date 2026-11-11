# M5 看门狗测试报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 结论：加载期与测试期看门狗均生效；NVFP4 加载、窗口基准与真实 smoke 全程未发生低内存事件。

---

## 1. 目标

模型服务器与 GLM-OCR/Layout 共用，35B 模型加载或 128K 请求可能耗尽统一内存。看门狗要求：

- 加载期：`MemAvailable` 低于阈值时终止**刚启动的模型进程**，保护宿主机与共用服务。
- 测试期：低于阈值时终止**测试客户端**，不杀模型服务。
- 内存读取失败时保守处理（连续失败视为触发）。
- 阈值可配置，可注入 clock/sleep 做单元测试。

---

## 2. 实现

| 组件 | 作用 |
|---|---|
| `services/agent/watchdog.py` | `MemoryWatchdog`：check/run/guard/terminate；`WatchdogTripped` |
| `scripts/dev/model-watchdog.py` | SSH 读取模型服务器 `MemAvailable`；load 模式可 kill 远程模型进程；test 模式 kill 本地测试进程 |
| `scripts/dev/qwen-load-watchdog.sh` | 模型服务器端加载守护；就绪（`/v1/models` 200）后自动退出 |
| `scripts/dev/guarded-model-test.py` | 启动测试命令并 guard；低内存终止测试命令 |

阈值：

- 加载期 floor：**8192 MiB**
- 测试/基准 floor：**4096 MiB**
- 检查间隔：2 s
- 单元测试 max_source_errors：3（连续 SSH 失败即保守触发）

---

## 3. 单元测试

`tests/integration/agent/test_watchdog.py` **4 passed**：

| 测试 | 结果 |
|---|---|
| 低于阈值触发 + on_trip 回调 | 通过 |
| SSH/内存源连续失败后触发 `memory_source_error` | 通过 |
| `guard` 在触发时终止子进程 | 通过 |
| `run(max_samples)` 正常采样退出 | 通过 |

---

## 4. 真实加载看门狗

启动命令：

```bash
vllm serve /home/grainuser/models/models/Qwen3.6-35B-A3B-NVFP4 \
  --port 9988 --served-model-name Qwen3.6-35B-A3B-NVFP4 \
  --language-model-only --max-model-len 131072 --max-num-seqs 4 \
  --gpu-memory-utilization 0.40 --kv-cache-dtype fp8 --enable-prefix-caching
```

守护日志（节选）：

```text
2026-11-11 23:13:07 pid=21745 available_mb=32896 floor_mb=8192
2026-11-11 23:13:09 pid=21745 READY; watchdog exiting
```

- 加载期间 `MemAvailable` 最低约 32.9 GiB，远高于 8 GiB。
- `/v1/models` 返回 200 后守护自动退出，避免误杀已就绪服务。

---

## 5. 测试期看门狗

| 测试 | floor | 最低可用内存 | 结果 |
|---|---:|---:|---|
| Qwen smoke | 4096 MiB | 32,901 MiB | 通过，未触发 |
| RouterAgent 评测 | 4096 MiB | 20,684 MiB | 通过，未触发 |
| 窗口基准（32K/64K/128K） | 4096 MiB | 20,660 MiB | 通过，未触发 |

窗口基准期间 128K 请求使可用内存从约 29.1 GiB 降到 20.6 GiB；仍在安全线以上。若继续下降，`guarded-model-test.py` 会终止基准客户端，模型服务保留。

---

## 6. 结论与 D-006

- 加载期 floor 8192 MiB、测试期 floor 4096 MiB 经实测可用。
- 看门狗只终止测试客户端，不杀模型服务；加载期才终止加载进程。
- 内存源连续失败按触发处理，避免“监控失效但继续压测”。
- D-006 建议回填：**测试内存下限 4096 MiB；模型加载下限 8192 MiB；检查间隔 2 s**。

---

## 7. 后续

1. 模型服务器提供内存指标 HTTP 接口后，可去掉 SSH 依赖。
2. 多并发压测时按 `max-num-seqs` 动态调整 floor（建议并发 4 时 6144–8192 MiB）。
3. 将看门狗事件写入 Prometheus/告警，纳入 M8 监控。
