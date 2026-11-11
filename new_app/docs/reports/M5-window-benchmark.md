# M5 窗口基准报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 模型：`Qwen3.6-35B-A3B-NVFP4` @ `192.168.1.35:9988`  
> 结论：默认窗口 **64K**；128K 可用但延迟与显存代价明显，作为上限保留。

---

## 1. 服务配置

| 项 | 值 |
|---|---|
| 模型 | `Qwen3.6-35B-A3B-NVFP4`（35B MoE，NVFP4 量化） |
| 端口 | 9988 |
| 权重 | `/home/grainuser/models/models/Qwen3.6-35B-A3B-NVFP4` |
| vLLM | `/home/grainuser/hansonDoc_RAG_deploy/venv/bin/vllm` |
| `max-model-len` | 131072 |
| `max-num-seqs` | 4 |
| `max-num-batched-tokens` | 65536 |
| `gpu-memory-utilization` | 0.40 |
| `kv-cache-dtype` | fp8 |
| 其他 | `--language-model-only`、`--enable-prefix-caching`、`--trust-remote-code` |

与 GLM-OCR（9977，0.16）并行运行；模型服务器内存 119 GiB，测试前可用约 32 GiB。

---

## 2. 方法

- 脚本：[window_benchmark.py](../../scripts/benchmark/window_benchmark.py)。
- 用模型服务器 `POST /tokenize`（根路径）精确计数，构造 32K/64K/128K 目标 prompt。
- 单请求、`temperature=0`、`max_tokens=32`、`enable_thinking=false`。
- 每次请求前后通过 SSH 读取 `MemAvailable`。
- 全程由 `guarded-model-test.py` 监控：**floor=4096 MiB**，低于阈值终止测试客户端，不杀模型服务。
- “128K”组实际构造 119,970 tokens，为输出预留空间（服务器上限 131,072）。

---

## 3. 结果

| 目标窗口 | 实际 prompt tokens | 延迟 | completion | 请求前可用内存 | 请求后可用内存 |
|---|---:|---:|---:|---:|---:|
| 32K | 31,995 | **11,518 ms** | 6 | 32,695 MiB | 29,146 MiB |
| 64K | 63,955 | **10,054 ms** | 6 | 约 29.1 GiB | 约 29.1 GiB |
| 128K | 119,970 | **26,405 ms** | 6 | 29,133 MiB | 20,660 MiB |

- 全部 HTTP 200；内容长度 12 字符（`{"ok": true}`）。
- 32K→64K 延迟没有线性增长（前缀缓存与批处理影响）；128K 预填明显变慢，内存下降约 8.5 GiB。
- 看门狗全程未触发；最低可用内存 20,660 MiB，远高于 4096 MiB 安全线。
- 原始数据：[M5-window-benchmark.json](M5-window-benchmark.json)。

---

## 4. 结论与 D-005

| 项 | 结论 |
|---|---|
| 默认上下文窗口 | **64K**（`AGENT_CONTEXT_WINDOW=65536`） |
| 最大窗口 | 128K（131,072），仅在长文档分段后按需使用 |
| 选择理由 | 64K 延迟约 10 s、内存稳定；128K 延迟 26 s、可用内存降至 20.6 GiB，留给并发/OCR 的余量更小 |
| 并发 | 服务器 `max-num-seqs=4`；本基准单请求串行；并发 4 的完整压测留待 M8 负载测试 |
| 与 GLM/Layout 共跑 | 本基准期间 GLM-OCR 9977 与 Layout 9978 保持运行，未中断 |

D-005 建议回填：**默认 64K，128K 作为上限**；若后续并发 4 下 64K 出现排队，再降为 32K。

---

## 5. 风险与后续

- 128K 请求会显著占用 KV cache；生产需限制单文档最大页数/表格数，并保留分段策略。
- 当前 `max-num-seqs=4` 与 `gpu-memory-utilization=0.40` 是 35B NVFP4 + GLM 共存的折中；若只跑 Qwen 可提高，但需重新压测。
- 并发 4、32K/64K/128K 的组合基准（Q2 完整要求）需在模型服务器空闲窗口补跑；本次单请求数据已满足 M5 出口的最低证据要求。
