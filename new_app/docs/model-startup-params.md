# 模型服务器启动参数（优化后配置）

> 更新：2026-11-26　服务器：**192.168.188.75**（hostname `spark-15b6`，原 192.168.188.75 已变更）  
> 启动顺序：**Qwen LLM → GLM-OCR → 版面 layout → DSH 代理**（与历史有序启动脚本一致）

## 快速启动（有序）

```bash
ssh grainuser@192.168.188.75
bash ~/restart_ordered_opt.sh
# 日志：~/start-logs/ordered_opt.log
# 就绪判定：9977 / 9978 / 9988 / 9989 全部返回 200（layout 用 /healthz）
```

脚本等价操作：
1. 清理旧进程（vllm / layout_api / dsh_llm_proxy）
2. 先启动 Qwen：`~/dsh-spark/start-vllm.sh`
3. 等待 Qwen 就绪后启动 GLM-OCR：`~/hansonDoc_RAG_deploy/scripts/start_glm_ocr.sh`
4. 最后启动 layout + DSH 代理

## 1) Qwen LLM（:9988）

启动脚本：`/home/grainuser/dsh-spark/start-vllm.sh`  
模型：`Qwen3.6-35B-A3B-NVFP4`（`~/models/models/Qwen3.6-35B-A3B-NVFP4`）

| 参数 | 值 |
|---|---|
| `--max-num-seqs` | **8** |
| `--max-num-batched-tokens` | **24576** |
| `--max-model-len` | **131072** |
| `--kv-cache-dtype` | **fp8** |
| `--gpu-memory-utilization` | **0.40**（≈48GB） |
| `--override-generation-config` | `{"temperature": 0.0, "top_p": 1.0, "top_k": -1}` |
| 其他 | `--enable-prefix-caching --enable-chunked-prefill --enable-prompt-tokens-details`、`--moe-backend auto`、`--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3` |

DSH 客户端并发：**6**（低于模型 8，不排队）。

## 2) GLM-OCR（:9977）

启动脚本：`/home/grainuser/hansonDoc_RAG_deploy/scripts/start_glm_ocr.sh`  
模型：`GLM-OCR`

| 参数 | 值 |
|---|---|
| `--max-num-seqs` | **6**（防 OOM，已从 8 降低） |
| `--max-num-batched-tokens` | **16384** |
| `--max-model-len` | **32768** |
| `--gpu-memory-utilization` | **0.22**（≈26GB） |
| `--kv-cache-dtype` | **fp8** |
| 采样 | `temperature=0.0, top_p=1.0, top_k=-1`，`--seed 0` |
| 其他 | `--enable-prefix-caching --enable-chunked-prefill` |

注意：启动环境需包含 **ninja**（`~/.local/bin` 与 `~/models/venv/bin`）；否则 flashinfer JIT 会因 `FileNotFoundError: ninja` 启动失败。

## 3) 版面 layout（:9978）

```bash
cd ~/hansonDoc_RAG
setsid nohup env CUDA_VISIBLE_DEVICES= backend/.venv/bin/python -m uvicorn layout_api.app:app \
  --host 0.0.0.0 --port 9978 > ~/start-logs/layout_last.log 2>&1 &
```

## 4) DSH LLM 代理（:9989）

```bash
cd ~/models
setsid nohup ~/models/venv/bin/python -m uvicorn dsh_llm_proxy:app \
  --host 0.0.0.0 --port 9989 > ~/start-logs/proxy_last.log 2>&1 &
```

作用：为 DSH 发往 Qwen 的请求注入 `enable_thinking=false`。

## 客户端并发（OCR）

| 环境变量 | 值 |
|---|---|
| `GLM_OCR_BASE_URL` | `http://192.168.188.75:9977/v1` |
| `GLM_OCR_MODEL` | `GLM-OCR` |
| `LAYOUT_BASE_URL` | `http://192.168.188.75:9978` |
| `OCR_LAYOUT_FIRST` | `true` |
| `OCR_DPI` | `150` |
| `GLM_OCR_PAGE_CONCURRENCY` | **6** |
| `GLM_OCR_MAX_CONCURRENCY` | **16** |
| `LAYOUT_BLOCK_CONCURRENCY` | **8** |

## 就绪验证

```bash
curl -s -o /dev/null -w '9988=%{http_code}\n' http://192.168.188.75:9988/v1/models
curl -s -o /dev/null -w '9977=%{http_code}\n' http://192.168.188.75:9977/v1/models
curl -s -o /dev/null -w '9978=%{http_code}\n' http://192.168.188.75:9978/healthz
curl -s -o /dev/null -w '9989=%{http_code}\n' http://192.168.188.75:9989/healthz

# 生效参数核对
ps -eo args | grep 'vllm serve' | grep Qwen  | tr ' ' '\n' | grep -A1 -E '^--(max-num-seqs|max-num-batched-tokens|max-model-len|gpu-memory-utilization)$'
ps -eo args | grep 'vllm serve' | grep -i GLM | tr ' ' '\n' | grep -A1 -E '^--(max-num-seqs|max-num-batched-tokens|max-model-len|gpu-memory-utilization)$'
```

## 实测（2026-11-25 20:26）

| 服务 | 端口 | 状态 | 生效参数 |
|---|---|---|---|
| Qwen LLM | 9988 | 200 | seqs=8 / batched=24576 / len=131072 / util=0.40 / kv=fp8 |
| GLM-OCR | 9977 | 200 | seqs=6 / batched=16384 / len=32768 / util=0.22 / kv=fp8 |
| layout | 9978 | 200（/healthz） | uvicorn layout_api |
| DSH 代理 | 9989 | 200 | dsh_llm_proxy |

## 客户端接入要点

- DSH 绑定远程：`HANSON_DSH_REMOTE=grainuser@192.168.188.75`（或脚本 `--remote`）
- 本地 OCR：`GLM_OCR_BASE_URL=http://192.168.188.75:9977/v1`、`LAYOUT_BASE_URL=http://192.168.188.75:9978`
- 原 192.168.188.75 已停用，所有模型调用改指 **192.168.188.75**
