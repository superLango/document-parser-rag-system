# 模型注册表

> 设备：`grainuser@192.168.1.35`（`spark-15b6`）
> 更新：2026-10-28
> 关联手册：`stages/09-模型服务与调用手册.md`

## 1. 设备

| 项 | 值 |
|---|---|
| 主机名 | `spark-15b6` |
| 内网 IP | `192.168.1.35/24`（2026-10-29 起） |
| 系统 | Ubuntu 24.04.4 LTS，aarch64 |
| GPU | NVIDIA GB10，驱动 580.126.09，CUDA 13.0 |
| 统一内存 | 119GiB |
| 当前 GPU 占用 | NIII 约 11GB + GLM 约 19GB + Qwen 9989 约 42GB（0.35 预算）+ 旁路 9990 约 20GB（2026-10-29 实测 98GB / 119GB，可用约 20GB） |

## 2. 模型

| 角色 | 模型 | 路径 | 大小 | 版本/哈希 | 运行时 | 端口 | 状态 |
|---|---|---|---|---|---|---|---|
| 版面分析 | PP-DocLayoutV3（微调 v2） | `/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3` | 133MB | SHA256 `5b76c1ff4b5b0305e8c6f7e09ae71fbe1f64740abb1e67a206e12d6e82c53cc3` | backend `.venv`（Python 3.13.12，torch 2.13.0，transformers 5.15.0） | 9978 | 运行中 |
| OCR | GLM-OCR | `/home/grainuser/hansonDoc_RAG_deploy/models/glm-ocr/GLM-OCR` | 2.5G | config SHA256 `4e1daf0d8a3f63e58960ac14bcb58b7be96758cad231fb7a1e5fec60f42dcd8c` | vLLM 0.26.0（`/home/grainuser/models/venv/bin/python3.12`） | 9977 | 运行中 |
| 抽取 | Qwen3.5-9B | `/home/grainuser/models/models/Qwen3.5-9B` | 19G | index SHA256 `26d3539b516be613f39563617cb9d33b3f83d401298125be392c80cefb8f7fe5` | vLLM 0.26.0 | 9989 | 未启动（训练期间停止，按需拉起） |
| 抽取（M2 旁路） | Qwen3.5-9B + `adapter-v2` | `/home/grainuser/hanson_m2/adapter-v2` | 116MB | SHA256 `89d63539ddd14e3a54f0759f9bab02a41c6a2f0aa0875fbc5999eb012c1ee110` | transformers 5.20.2 + peft 0.21.2（`grain_ultra`） | 9990 | 运行中（评测用，v2 约束版） |
| RAG 自用 | Qwen3.6-35B-A3B-FP8 | `/home/grainuser/hansonDoc_RAG_deploy/models/qwen36/Qwen3.6-35B-A3B-FP8` | — | — | vLLM 0.26.0 | 9988 | 未启动 |
| 嵌入 | bge-m3 | `hansonDoc_RAG/models/bge-m3` | — | — | 进程内 | — | 未启动 |
| 重排 | bge-reranker-v2-m3 | `hansonDoc_RAG/models/bge-reranker-v2-m3` | — | — | 进程内 | — | 未启动 |

`models/doclayout_yolo/` 是历史权重，当前代码已移除该引擎，不要使用。

### 2.1 M2.3 LoRA adapter（`adapter-v2` 在用，均未上线）

| 项 | adapter-v2（当前） | adapter-v1（历史） |
|---|---|---|
| 基座 | `Qwen3.5-9B` | 同左 |
| 路径 | `/home/grainuser/hanson_m2/adapter-v2` | `/home/grainuser/hanson_m2/adapter-v1` |
| 权重 SHA256 | `89d63539ddd14e3a54f0759f9bab02a41c6a2f0aa0875fbc5999eb012c1ee110` | `d97807a40524eee374f45c2d761dccb60b2e90b8d683bb85b635070d4dbe82b4` |
| 训练报告 SHA256 | `a159f7a2aefebcb52ae08fee965bec628728ca9741e7104b4128c2203082f86d` | `29eb9b8b7927da57cfa050211a66e0c96a959cb692896ff0e481efc31c3fbf16` |
| 数据 | `sft-v2` 692/110；train `05a2bece…`、eval `b6378475…`（约束版表头 + 金标规范化） | `sft-v1` 692/110；train `0a6a0afb…`、eval `55cc777a…` |
| 超参 | 2 epoch、batch 1、grad_accum 16、max_seq 1536、lr 1e-4 cosine、bf16 | 2 epoch、batch 1、grad_accum 16、max_seq 1280 |
| 指标 | train_loss 0.0592；eval_loss 0.0739（epoch2）；1725s | train_loss 0.0611；eval_loss 0.0678→0.0695；1701s |
| LoRA | r=16 / alpha=32 / dropout=0.05；7 类线性层；peft 0.21.2 | 同左 |
| 状态 | 9990 正在服务；`sft_m2` 管线与 `adapter-v1 + native` 结果逐文档一致，仍低于 base+native 0.0115 | 保留作对照，不再服务 |

| 项 | 值 |
|---|---|
| 训练环境 | conda `grain_ultra`，torch 2.9.1+cu130，transformers 5.20.2；chat messages，prompt 段 label 置 -100 |
| 入口 | `training/m2_lora/train_lora.py` + `training/m2_lora/run_m2_lora.sh`（`DATA_DIR` / `OUTPUT` / `MAX_SEQ` 可覆盖） |
| 推理参数 | `training/m2_lora/inference_params.json`（`lora-infer-v1`）：greedy、`enable_thinking=false`、max_new_tokens 512 |
| 服务 | `training/m2_lora/serve_adapter.py`，`/health` 返回实际 adapter 名 |



## 3. 启动脚本

| 服务 | 脚本 | 说明 |
|---|---|---|
| GLM-OCR | `/home/grainuser/hansonDoc_RAG/scripts/start_glm_ocr.sh` | 需先把 deploy venv 加入 PATH，否则 flashinfer 找不到 `ninja` |
| Qwen3.5-9B | `/home/grainuser/metal-doc-agent-runtime/start_qwen35_9b.sh` | 本项目新增，端口 9989 |
| Layout API | `/home/grainuser/metal-doc-agent-runtime/start_layout_api.sh` | 本项目新增，端口 9978 |
| LoRA 旁路 | `nohup python /home/grainuser/hanson_m2/code/serve_adapter.py --model /home/grainuser/models/models/Qwen3.5-9B --adapter /home/grainuser/hanson_m2/adapter-v1 --params /home/grainuser/hanson_m2/code/inference_params.json --port 9990` | 本项目新增，端口 9990，与 9989 并存 |

GLM-OCR 正确启动方式：

```bash
cd /home/grainuser/hansonDoc_RAG
export PATH=/home/grainuser/hansonDoc_RAG_deploy/venv/bin:$PATH
bash scripts/start_glm_ocr.sh --detach
bash scripts/start_glm_ocr.sh --check
```

## 4. 2026-10-26 验证结果

### 4.1 GLM-OCR

- `GET /v1/models`：返回 `GLM-OCR`，`max_model_len=32768`
- 实际 OCR：Q-Du 302 第 5 页，表格 prompt
- HTTP 200；返回 1230 字符；含 `<table>`；含 `430`
- 注：整页送模型时，模型把表下方正文也并入表格；M1-S2 应使用 layout bbox 裁剪后再送

### 4.2 Qwen3.5-9B

- `GET /v1/models`：返回 `Qwen3.5-9B`，`max_model_len=32768`
- 非 thinking 简单请求：`ok`
- JSON 模式：合法 JSON；无 `<think>`；解析出 `grade=2A14`、`Rm`、`A`
- 启动参数含 `--language-model-only --reasoning-parser qwen3 --gpu-memory-utilization 0.25`

### 4.3 Layout API

- `GET /health`：`status=ok`、`model_loaded=true`、`device=cuda:0`、`failures=0`
- `POST /v1/layout`：Q-Du 302 第 5 页
- 28 个 block；类型含 image/text/title/table；table 位于 order 8，bbox `[0.1286, 0.4488, 0.9009, 0.5338]`，confidence 0.9632
- `page_failures=[]`

### 4.4 笔记本侧连通性

- 历史记录：2026-10-27 主机地址曾恢复为 `192.168.188.75`，SSH 22 可达；`9977/9978/9989` 当时均未监听，需按手册 4.1/4.3 重新启动
- 2026-10-28 曾在 `192.168.1.35` 实测：SSH 可达；`9977` 返回 `GLM-OCR`、`9978` 健康检查 `model_loaded=true`、`9989` 返回 `Qwen3.5-9B`（`max_model_len=16384`）
- 历史：2026-10-28 曾在 `192.168.188.75` 启动三服务并完成真实 PDF 验收
- Qwen 抽取此前已在 `192.168.1.35:9989` 完成 20 份全量跑与 GB/T 1591 复跑；当前地址已切回该 IP
- 2026-10-28 切回后重启三服务：`9977` GLM-OCR、`9978` layout、`9989` Qwen3.5-9B 均 ready（笔记本侧 HTTP 200）

## 5. 运行约束

- 不要停 NIII 的 PID 2121/2122；
- 35B（9988）与 9B（9989）不要同时启动；
- **9989 必须先于 9990 启动**：反序时 vLLM 会报 `No available memory for the cache blocks`（0.35 预算≈41.6GB，扣掉 19GB 权重后不足以分 KV），表现为 `Engine core initialization failed`；
- **9990 只允许单实例**：重复 nohup 会叠 20GB/实例；2026-10-29 因双实例 + 9989 + OCR 导致内存 119/119、swap 15/15、load 94，SSH banner 超时，停 OCR 后恢复；
- 9989 与 9990 当前可共存（占用 98/119GB、可用约 20GB），不要再叠加第三个 9B 实例；离线评测（markdown 管线，OCR=mock）可先停 9977 释放约 19GB；
- Qwen3.5 默认 thinking，抽取请求必须 `chat_template_kwargs.enable_thinking=false`；
- 当前 9989 + 9990 共存占用约 98GB / 119GB，余量约 20GB，足够 layout 与评测；
- 模型服务均为 `nohup` 后台进程，重启机器后需重新启动。

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-26 | 首次登记；三服务启动并完成 smoke；新增 Qwen3.5-9B 与 Layout API 脚本 |
| 2026-10-26 | 主机 IP 由 `192.168.188.75` 变更为 `192.168.1.35`；Qwen3.5-9B 重新启动并完成 GB/T 1591 复跑 |
| 2026-10-27 | 主机 IP 恢复为 `192.168.188.75`；SSH 可达，`9977/9978/9989` 均未监听，待重新启动 |
| 2026-10-27 | 模型设备由 192.168.188.75 变更为 192.168.1.35；模型服务地址同步更新 |
| 2026-10-28 | 主机 IP 变更为 `192.168.43.7`；重新启动 9977/9978/9989 并更新配置与文档 |
| 2026-10-28 | Qwen 改为 `16K / 0.35 / 2 seq` 后 ready；Q-Du 302 真实 PDF 10 页跑通（5 表/3 记录/59 证据，58 条 bbox）；平台预览与证据高亮验收通过 |
| 2026-10-28 | 主机 IP 由 `192.168.43.7` 变更为 `192.168.188.75`；三服务在 188.75 已就绪（9977 GLM-OCR、9978 layout、9989 Qwen 16K），文档与配置同步 |
| 2026-10-28 | 主机 IP 由 `192.168.188.75` 变更为 `192.168.43.7`；三服务在 43.7 实测就绪，平台与 smoke 配置同步 |
| 2026-10-28 | 主机 IP 由 `192.168.43.7` 变更为 `192.168.1.35`；配置、smoke 默认值与文档同步 |
| 2026-10-28 | M2.3 首次全量训练（batch 4 / max_seq 2048）跑到第 3 步后整机硬挂，23:39 重启；无 OOM/内核日志，推断统一内存耗尽 |
| 2026-10-29 | M2.3 保守配置重跑完成：batch 1 / grad_accum 16 / max_seq 1280，88 步 1701s，train_loss 0.0611、eval_loss 0.0695，产出 `adapter-v1` |
| 2026-10-29 | 主机 IP 由 `192.168.1.35` 变更为 `192.168.188.75`；模型设备重启一次，`adapter-v1` 与数据保留；训练入口与评测脚本同步改用新地址 |
| 2026-10-29 | 新增 9990 旁路服务（transformers + `adapter-v1`）；5 份 heldout 管线 A/B：field F1 0.744 vs 基线 0.7555，record/coverage/幻觉持平；9989 本次启动报 `Engine core initialization failed` 未起 |
| 2026-10-29 | 9989 失败根因定位为 KV 预算不足（9990 先占 20GB）；改为 9989 先起、9990 后起，两服务共存（98/119GB） |
| 2026-10-29 | 补全 `allowed_properties` 约束样本并重训 `adapter-v2`（sft-v2，max_seq 1536）；9990 切换为 v2；`sft_m2` 管线 field 0.6909→0.7440，与 `adapter-v1+native` 逐文档一致 |
| 2026-10-29 | 映射投票（`vote`）上线为可选开关：双路映射 + 规则优先，5 份 heldout field 0.7555、header 73，与 base+native 逐文档一致；9990 重复实例引发内存耗尽，停 OCR 后恢复 |
| 2026-10-29 | 主机 IP 由 `192.168.188.75` 变更为 `192.168.1.35`；SSH 可达但 `9989` 未监听，按 `start_qwen35_9b.sh` 重启 Qwen3.5-9B 后 ready |
