# 模型平面：GLM-OCR + parsekit 版面服务（PP-DocLayoutV3）

引擎真实链路依赖三个模型服务：

| 端口 | 服务 | 启动脚本 | 说明 |
|---|---|---|---|
| `9977` | GLM-OCR（vLLM） | `start_glm_ocr.sh` | 块级 OCR；`max-num-seqs 8` / `max-num-batched-tokens 16384`，无前缀缓存、无 MM 缓存 |
| `9979` | PP-DocLayoutV3（GPU） | `start_layout_gpu.sh` | 引擎 **主** 版面服务（`LAYOUT_SERVICE_URL`） |
| `9978` | PP-DocLayoutV3（CPU） | `start_layout.sh` | 引擎 **备** 版面服务（`LAYOUT_SERVICE_FALLBACK_URL`） |
| `9991` | Qwen3.5-9B + adapter-v5 | `hanson_m2/code/run_vllm_lora.sh` | SFT 抽取（由 hanson_m2 负责） |

## 契约

| 端点 | 说明 |
|---|---|
| `GET /health` | 返回 `status/loaded/model_dir/device`；模型未加载时 `degraded` |
| `POST /v1/layout` | 入参 `image_base64/page_index/dpi/width/height`；出参 `blocks[{type,bbox,order,confidence,structural}]`，`bbox` 为 `[0,1]` 归一化 |

可选共享令牌：设置 `LAYOUT_SERVICE_TOKEN` 后，`POST /v1/layout` 需要请求头 `X-Layout-Token`；引擎通过同名环境变量自动携带。

## 部署到 192.168.188.75

```bash
scp infra/model-plane/serve_layout.py infra/model-plane/start_layout.sh \
    infra/model-plane/start_layout_gpu.sh infra/model-plane/start_glm_ocr.sh \
    grainuser@192.168.188.75:/home/grainuser/hanson_m2/code/

# 版面：GPU 主服务（:9979）+ CPU 备服务（:9978）
cd /home/grainuser/hanson_m2/code
setsid nohup bash start_layout_gpu.sh 9979 > logs/layout_gpu.log 2>&1 < /dev/null &
setsid nohup bash start_layout.sh 9978 > logs/layout.log 2>&1 < /dev/null &
curl -s http://127.0.0.1:9979/health; curl -s http://127.0.0.1:9978/health

# OCR：停旧进程后按调优参数启动（2026-11-02 选定 12 / 8192）
pkill -f 'vllm serve .*GLM-OCR' || true
setsid nohup bash start_glm_ocr.sh 12 8192 > logs/glm_ocr_start.log 2>&1 < /dev/null &
```

`start_glm_ocr.sh` 会显式补齐 `PATH`（`~/.local/bin`、venv `bin`、`/usr/local/cuda/bin`），否则
flashinfer 在新 batch 形状上做 JIT 时找不到 `ninja`，服务会启动失败。

### 重启后的预热

vLLM/flashinfer 对首次出现的 batch 形状会做 JIT（GB10 上可能耗时数分钟，期间请求会超时）。
重启后先用 1/4/8 并发各跑一轮小图，或在正式任务前跑一份短文档，避免首个真实任务踩到编译尖峰。

## 引擎侧配套配置

```yaml
LAYOUT_SERVICE_URL: http://192.168.188.75:9979            # GPU 主
LAYOUT_SERVICE_FALLBACK_URL: http://192.168.188.75:9978   # CPU 备（超时/失败自动切换）
LAYOUT_TIMEOUT: 60
OCR_MAX_INFLIGHT: 16                                    # 客户端总并发上限（对齐 OCR 服务）
```

引擎在版面上串行调用（服务端本身单实例串行），OCR 并发由 `OCR_MAX_INFLIGHT` 控制。

## 实测（2026-11-01）

| 项目 | 结果 |
|---|---|
| 版面单页 | GPU 0.27–0.6s；CPU 1.0–2.0s（同页同块数，类型/数量一致） |
| OCR 吞吐 | 表块基准（4 类、16 并发）：`max-num-seqs=2` ≈ 20 req/min；`=8` ≈ 62–68 req/min；`=12` ≈ 85 req/min |
| 端到端（r6-10） | 37 页扫描件 **234s**；22 页文本层 **80s**；23 页表格密集 **358s**（含表格长响应重试） |
| 全量（r6-10，25 份/434 页） | 总 6559s，15.1s/页；中位 8.6s/页；≤30 页文档 18/21 ≤300s；超大表格文档 389–2266s（单块 300–500s） |
| **全量复跑（2026-11-02，.75+host）** | **25/25 成功、434 页、1764s（4.06s/页）；中位 3.33s/页、p95 5.6s/页；全部文档 ≤300s（最慢 222s）；失败块 0** |
| 2026-11-02 迁移 .75（seq12/8192/prefix/gpu0.4） | 同文档同引擎，**host 网络**：doc_02 11s、doc_07 141s、doc_12 68s、doc_08 239s；对比旧机 11.4/185.6/100.0/2266s，长表提升 24–89% |
| 网络对比（同一 .75 服务） | Docker bridge：doc_02 101s、doc_07 553s、doc_12 428s；host 网络：11/141/68s。bridge/NAT 会让图片+流式请求间歇挂 90s |
| 已知问题 | Docker bridge 跨子网（.189→.188）访问模型服务时，图片 OCR 响应会间歇 90s 不返回（流式与非流式都出现）；worker 已改 `network_mode: host`。`GLM_OCR_TIMEOUT` 是空闲读超时，超大表格仍会连续生成数分钟 |

## 显存说明（本机实测）

同一张 GB10（119GB 统一内存）同时运行 GLM-OCR（`0.4`）与 Qwen LoRA（`0.38`）后，仅余 ~4–5GB 给系统，
服务可运行但无余量：Qwen 低于 0.38 时曾因 KV cache 空间不足启动失败。版面 GPU 服务占用很小，可与 vLLM 共存；
CPU 版面服务受 vLLM 主机侧线程争抢影响，在 OCR 满载时单页可达数秒甚至超时，因此生产以 GPU 版面为主、CPU 版面为备。

## 验证

```bash
curl -s -X POST http://192.168.188.75:9979/v1/layout \
  -H 'Content-Type: application/json' \
  -d "{\"image_base64\":\"$(base64 -w0 page.png)\",\"page_index\":1,\"dpi\":200}" | head -c 500
```

服务端单实例串行推理（`_engine_lock`），避免多 worker 并发争抢同一模型实例。
模型目录：`/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3`；依赖使用
`/home/grainuser/hansonDoc_RAG/backend/venv/bin/python`（已含 transformers/torch/Pillow/FastAPI）。

