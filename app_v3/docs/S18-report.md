# app_v3 S18 阶段报告（新服务器 IP 启动模型 + 条款通道起步）

> 阶段：P1（修订版）S18  
> 日期：2026-11-26  
> 服务器：**192.168.188.75**（原 192.168.1.35 变更，hostname `spark-15b6`）  
> 状态：S18 进行中；模型已按冻结文档启动，全局 G1 仍未达标

## 1. 模型服务器启动（已完成）

按 `new_app/docs/model-startup-params.md` 的有序脚本启动：
`bash ~/restart_ordered_opt.sh`

| 服务 | 端口 | 就绪 | 启动耗时/说明 |
|---|---|---:|---|
| Qwen LLM | 9988 | ✅ 200 | 246s 就绪；seqs=8 / batched=24576 / len=131072 / util=0.40 |
| GLM-OCR | 9977 | ✅ 200 | 已就绪；seqs=6 / batched=16384 / len=32768 / util=0.22 |
| layout | 9978 | ✅ `/healthz` 200 | uvicorn layout_api |
| DSH 代理 | 9989 | ✅ 200 | dsh_llm_proxy（注入 enable_thinking=false） |

从 Windows 客户端直连 `http://192.168.188.75:{9988,9977,9978,9989}` 全部返回 200。  
已同步更新客户端默认地址：
- `app_v3/channels/llm_client.py` → `http://192.168.188.75:9989/v1`
- `app_v3/scripts/s11_rebind.py` / `s12_full_pipeline.py` → `grainuser@192.168.188.75`
- `new_app/scripts/dev/dsh_bind.py`、`new_app/services/agent/config.py`、benchmark 默认地址
- `new_app/docs/model-startup-params.md` 全量替换为 192.168.188.75

## 2. S18 新增：条款通道（clause）

`channels/clause_channel.py`：
- 按页把 OCR markdown 切块（4 页/块）；
- 模型抽取带证据的规范要求记录（JSON 数组，含 category/item/grade/requirement/unit/conditions/page/evidence）；
- 支持并发与 JSON 容错。

首测（gbt-8547）：40 条条款记录，评测 3/9 匹配、多余 37 → **暂不并入主结果**，需要过滤/证据校验。

## 3. S18 过滤实验（原生记录二次过滤）

在 S17 质量过滤基础上增加：
1. 原生记录"新键"规则：只保留 `(类别,项目,牌号)` 不在 base 中的原生记录（移除以同键不同值的重复记录）；
2. 物理合理性规则：拉伸性能超范围、化学成分 >100 等过滤。

结果：
- 全局：6935/9724（71.32%）、一致率 0.8017、多余 2349；
- 相比 S17 quality2（6938/71.35/0.8017/2427）：匹配 -3、多余 -78。

## 4. 当前最佳（未变化）

| 方案 | 匹配 | 一致率 | 覆盖率 | 多余 |
|---|---:|---:|---:|---:|
| S17 quality2 | **6938** | **0.8017** | **71.35%** | 2427 |
| S18 二次过滤 | 6935 | 0.8017 | 71.32% | 2349 |

G1（覆盖率≥72%、一致率≥0.80、多余<2000）仍未通过：覆盖率差约 63 条匹配，多余超 427。

## 5. 下一步（S18 继续）

1. 条款通道仅保留通过证据校验/与 base 项目一致的高置信记录，补高倍/热处理/弯曲缺口；
2. 对 gbt-3620、astm、gbt-14976、asme、gbt-3077 做定向原生/条款抽取，补约 63 条匹配；
3. 继续压多余 427（基础记录质量 + 原生冲突过滤）；
4. 达标后冻结并启动盲测。
