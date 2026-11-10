# 模型平面（1.35）与 GPU 池

模型进程**不部署在业务 K8s 集群**。1.35 作为独立模型平面，K8s 通过 HTTP 访问：

| 池 | 端点 | 节点标签/污点 | 说明 |
|---|---|---|---|
| OCR 池 | `http://192.168.188.75:9977`（GLM-OCR）、`:9978`（PP-DocLayoutV3） | `gpu-pool=ocr:NoSchedule` | 生产优先 |
| 抽取池 | `http://192.168.188.75:9989`（Qwen 基座）、`:9990`（adapter shim） | `gpu-pool=extract:NoSchedule` | 生产/探索共享，按并发配额 |
| 探索池 | 复用抽取池，低优先级 | - | 不阻塞生产 |

## 启动顺序（内存约束）

1. 先起 `9989`（基座），确认 `/v1/models` 可用；
2. 再起 `9990`（adapter shim），且**只允许一个实例**；
3. OCR（`9977/9978`）可常驻；离线评测期间可停 OCR 释放约 19GB 内存。

违反顺序会出现 `No available memory for the cache blocks`，或整机内存 119/119、swap 打满。

## GPU 隔离

- 模型节点打 `gpu-pool=ocr|extract:NoSchedule` 污点，仅模型 Pod 容忍；
- 业务 Pod 不打 GPU 资源请求，避免占用显存；
- 抽取池并发由 `--max-num-seqs` 与每任务并发（`QWEN_CONCURRENCY`）共同限制；
- 生产请求优先：探索任务只允许在 `worker-explore`（`METAL_DOC_ORCHESTRATE=0`）上运行，并用独立模型端点或低并发配额。

## 度量

模型侧暴露 Prometheus 指标（vLLM 自带 `/metrics`），在 `infra/monitoring/prometheus-rules.yaml` 中按 `instance` 抓取；GPU 利用率与显存由 `nvidia-smi-exporter` 或 DCGM exporter 提供。
