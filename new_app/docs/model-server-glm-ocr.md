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
