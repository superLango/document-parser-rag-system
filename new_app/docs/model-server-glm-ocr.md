# 模型服务器 GLM-OCR 启动手册

> 来源：`legacy/metal-standard-agent-plan/stages/09-模型服务与调用手册.md`  
> 设备：`grainuser@192.168.1.35`（主机名 `spark-15b6`）  
> 端口：`9977`，模型名 `GLM-OCR`  
> 记录日期：2026-11-11（实测启动成功）

## 1. 设备与资产

| 项 | 值 |
|---|---|
| 系统 | Ubuntu 24.04 LTS，aarch64，NVIDIA GB10，统一内存 119GiB |
| SSH | `ssh grainuser@192.168.1.35`（需已授权私钥） |
| 权重 | `/home/grainuser/hansonDoc_RAG_deploy/models/glm-ocr/GLM-OCR` |
| 启动脚本 | `/home/grainuser/hansonDoc_RAG/scripts/start_glm_ocr.sh` |
| vLLM 入口 | `/home/grainuser/hansonDoc_RAG_deploy/venv/bin/vllm`（vLLM 0.26.0） |
| API | OpenAI 兼容 `/v1/chat/completions`、`/v1/models` |

## 2. 启动

```bash
ssh grainuser@192.168.1.35
cd /home/grainuser/hansonDoc_RAG
export PATH=/home/grainuser/hansonDoc_RAG_deploy/venv/bin:$PATH

bash scripts/start_glm_ocr.sh --detach
bash scripts/start_glm_ocr.sh --check
curl -s http://127.0.0.1:9977/v1/models
```

> 必须先导出 `PATH`。否则 flashinfer JIT 找不到 `ninja`，EngineCore 初始化失败。
> 首次加载约 1–3 分钟，日志：`hansonDoc_RAG/logs/vllm_glm_ocr_9977.log`。

脚本实际执行：

```bash
cd /home/grainuser/hansonDoc_RAG_deploy
nohup venv/bin/vllm serve models/glm-ocr/GLM-OCR \
  --host 0.0.0.0 --port 9977 --served-model-name GLM-OCR \
  --trust-remote-code --max-num-seqs 2 --max-num-batched-tokens 8192 \
  --max-model-len 32768 --enable-prefix-caching --enable-chunked-prefill \
  --gpu-memory-utilization 0.16 --kv-cache-dtype fp8 \
  > ../hansonDoc_RAG/logs/vllm_glm_ocr_9977.log 2>&1 &
```

## 3. 版面服务（9978）

| 项 | 值 |
|---|---|
| 代码 | `/home/grainuser/metal-doc-agent-runtime/layout_api.py` |
| 启动脚本 | `/home/grainuser/metal-doc-agent-runtime/start_layout_api.sh` |
| 权重 | `/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3`（PP-DocLayoutV3） |
| 端口 | `9978` |

```bash
cd /home/grainuser/metal-doc-agent-runtime
bash start_layout_api.sh --detach
bash start_layout_api.sh --check
curl -s http://127.0.0.1:9978/health
```

`/health` 返回 `model_loaded=true` 即就绪。新架构通过 `LAYOUT_BASE_URL=http://192.168.1.35:9978` 调用 `/v1/layout`，请求体为 `page_index/width/height/dpi/image_base64`。

## 4. 停止

```bash
kill $(cat /home/grainuser/hansonDoc_RAG/logs/glm_ocr_9977.pid)
```

## 4. 约束

- **不要杀 NIII 进程**：GPU 上 `/data/niii_pro_inclusion`、`/data/niii_pro_metallographic` 不属于本项目。
- **不要同时启动 35B 与 9B**：35B（0.50）+ 9B（0.25）+ GLM（0.16）会超出显存预算。
- 停止时只针对 9977，避免误杀 RAG 的 9988。

## 5. 新架构配置

| 变量 | 值 |
|---|---|
| `GLM_OCR_BASE_URL` | `http://192.168.1.35:9977/v1` |
| `GLM_OCR_MODEL` | `GLM-OCR` |
| `OCR_BACKEND` | `auto`（配置 GLM 后 PDF 自动走 GLM） |

Compose 与 K8s ConfigMap 已内置上述默认值，可通过环境变量覆盖。

## 6. 验证

```bash
# 模型服务 + 容器连通 + GLM 识别（Compose）
bash new_app/scripts/dev/glm-smoke.sh

# K8s 内 Markdown / PDF / 端到端 / GLM
bash new_app/scripts/dev/k8s-ocr-check.sh
```

请求示例：

```bash
curl -s http://192.168.1.35:9977/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "GLM-OCR",
    "messages": [{"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,<...>"}},
      {"type": "text", "text": "请将图片中的表格完整识别并转换为 HTML <table> 格式输出。"}
    ]}],
    "max_tokens": 4096,
    "temperature": 0
  }'
```

## 7. 实测记录

| 日期 | 结果 |
|---|---|
| 2026-11-11 | 9977 未运行（上次为正常关闭）；执行 `start_glm_ocr.sh --detach` 后约 1 分钟就绪，PID 12300 |
| 2026-11-11 | `/v1/models` 返回 `GLM-OCR`，`max_model_len=32768` |
| 2026-11-11 | Compose 与 K8s OCR 均完成真实 PDF 表格识别，`profile=mechanical_properties`，3×3 |

## 8. 网络稳定性问题与修复（2026-11-12）

**现象**：容器内 OCR 偶发 90s 读超时，大表块（约 96KB）连续两次超时后第三次成功，单文档 OCR 最长 195s；服务端日志显示请求最终 200 OK，引擎只在最后十几秒看到请求。

**根因**：WSL2 使用 `networkingMode=mirrored`，Windows 与 WSL 共用同一个 IP/MAC（`192.168.189.252` / `f8:fe:5e:9f:ec:a0`）。Docker 网桥在这层之上做 NAT，服务端返回容器的包会间歇性丢失，表现为请求发出后收不到响应、客户端 `FIN-WAIT-1` 的 FIN 一直不被 ACK。

**证据**：

| 路径 | 结果 |
|---|---|
| 模型服务器本机回环（同一图片、并发 2） | 40/40 成功，max 5.4s |
| Windows 主机 / WSL 主机直连 | 0 次超时 |
| Docker 默认网桥容器 | 约 31/282 次 90s 超时 |
| Docker host 网络容器 | 0/40、0/40 |
| 网桥 MTU 改 1492、关闭网卡 offload | 仍超时，排除 MTU/offload |

**修复**：`C:\Users\lango\.wslconfig` 改为 `networkingMode=nat`，执行一次 `wsl --shutdown` 生效。Docker 与 compose 服务（`restart: unless-stopped`）自动恢复。

**验证**：

- 网桥容器压测 2 轮 × 40 请求：**0 超时**，p50 5.7–5.8s（修复前每 40 次有 4–10 次 90s 超时）。
- AMS4108G OCR 回放 3 轮：**11.6s / 11.6s / 10.4s**，所有块首次成功（修复前 195.3s）。
- 真实 run `b5a6b4e7...`：20s 完成，`STRUCTURED_READY`。

OCR 适配器的 3 次重试保留，作为链路抖动的兜底，不再是主路径依赖。

### 8.1 模型服务器切换到 192.168.1.35（2026-11-12）

- 启动：`scripts/start_glm_ocr.sh --detach`（9977）、`start_layout_api.sh --detach`（9978），两者 `--check` 均 ready。
- Compose 默认地址改为 `http://192.168.1.35:9977/v1` 与 `http://192.168.1.35:9978`，OCR 容器已重建并确认环境变量生效。
- **第二个网络根因**：WSL 内 Docker 网络 `metal-agent_default` 占用 `192.168.0.0/20`，覆盖了模型服务器 `192.168.1.35`，且该网桥已 linkdown。WSL/容器访问新服务器时报 `No route to host`，OCR 因此回退到 PDF 后端并触发 `DOC-NO-RECORDS`。
- 修复：`docker network rm metal-agent_default`（无容器占用）；WSL 主机与 OCR 容器均可直连 9977/9978（200，60–160ms）。
- 复测：AMS4108G `STRUCTURED_READY`（19s，恢复 `layout_first` 与 2 records）；ASTM B338 `STRUCTURED_READY`（52s）。
