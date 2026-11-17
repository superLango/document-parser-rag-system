# 内网问题反馈 → 本地优化 → 算法回传 闭环方案

> 版本：v1（2026-11-16）
> 适用环境：应用栈部署在 193.168.2.201（无外网），Qwen 在 202；本地开发机为 Windows + WSL。
> 目标：把内网台账涉及的文档与算法导出到本地复现，优化后只回传算法资产，以内网可审计、可回滚的方式上线。

## 1. 设计原则

1. **只回传算法资产，不回传镜像**：解析规则通过 `parser_core` 资产热加载，新版本只需发布资产并移动 `stable` 指针，下一次解析自动生效，无需重启容器。
2. **不可变版本**：每个资产版本一旦发布不可覆盖，只能用新版本号；回滚靠切换通道指针。
3. **全链路可核验**：导出包、回传包都带 `manifest.json` + `SHA256SUMS`，传输前后各校验一次。
4. **先基线后优化**：本地必须先用“导出时的 stable 版本”复跑出基线，再对比候选版本，避免把环境差异误判为算法改进。
5. **台账闭环**：每条反馈最终落到「修复版本 + 验证 run_id + 结论」，可追溯到具体资产版本。

## 2. 现有能力（可直接复用）

| 能力 | 位置/接口 | 用途 |
|---|---|---|
| 台账数据 | 表 `feedback`（含 `document_id`、`run_id`、`category`、`description`、`status`） | 圈定导出范围 |
| 原始 PDF | `GET /v1/documents/{id}/file` | 导出原文 |
| 解析产物 | 表 `artifacts`（role：`markdown.md`、`records`、`ocr`、`tables.json`、`layout.json`、`review` 等） | 导出 md/表格/结构化结果 |
| 重新解析 | `POST /api/v1/integration/retrigger` | 新算法上线后复跑原任务，不必重新上传 |
| 资产发布 | `POST /internal/assets`（recipe-registry:8005） | 发布新版本 |
| 通道晋升 | `POST /internal/assets/parser/{id}/versions/{v}/promote` | `candidate → stable` |
| 通道回滚 | `POST /internal/assets/parser/{id}/rollback` | 秒级回退 |
| 资产落盘 | 201 主机 `data/recipe_registry/`（rw 挂载） | 备份/回滚兜底 |
| 发布脚本 | `new_app/scripts/assets/publish_parser_asset.py` | 发布+晋升 |

当前现场：`parser_core@1.7.40` 为 stable，沙箱每次运行按 stable 指针拉取并校验。

## 3. 总体流程

```
内网 201                          离线介质                  本地 WSL
┌─────────────────┐          ┌──────────────┐        ┌──────────────────┐
│ A. 导出台账+文档 │  ──────► │ B. 审批/校验  │ ─────► │ C. 复现基线       │
│    算法资产快照  │          │  SHA256 校验  │        │ D. 优化+candidate │
└─────────────────┘          └──────────────┘        └────────┬─────────┘
        ▲                                                      │ 只回传算法包
        │            ┌──────────────┐        ┌─────────────────▼────────┐
        └────────────│ E. 校验/发布 │ ◄───── │ 算法资产包 + 回归报告     │
                      │ 回滚预案     │        └──────────────────────────┘
                      └──────────────┘
```

## 4. 阶段 A：内网导出（201）

### A1. 台账导出

- 在「问题台账」两个 tab 分别按时间段导出 CSV（沿用现有导出功能）。
- 同时导出一份机器可读版本，字段固定为：
  `feedback_id, document_id, run_id, category, target, description, expected_value, source_quote, status, created_at, messages_count`
- 建议只导出 `status in (open, verified, fixed)` 且落在时间窗内的记录。

### A2. 文档包（按台账圈定）

以台账中的 `document_id` 去重，逐份导出：

```
documents/<document_id>/
  meta.json                     # 文件名、sha256、页数、创建时间
  original.pdf                  # 原始文件（/v1/documents/{id}/file）
  runs/<run_id>/
    run.json                    # 状态、parser 版本、channel、trace_id
    markdown.md                 # OCR/解析后的 md
    records.json                # 结构化结果
    tables.json / layout.json   # 表格与版面（问题定位用）
    review.json                 # 复核发现
    feedback.json               # 该 run 关联的台账条目
```

实现方式：在 201 的部署包内新增 `scripts/export_feedback_bundle.py`，直接读 PostgreSQL + MinIO（容器内执行，不依赖浏览器导出），避免人工逐份下载。

### A3. 算法资产快照

```
algorithms/
  parser_core/<stable_version>/          # 9 个 py + dictionary_data.json + manifest.json
  registry/recipes/                      # 配方
  registry/templates/                    # 模板
  dictionary/business_dictionary.json    # 业务词典
  prompts/                               # Agent 提示词（若与算法强相关）
  versions.json                          # 镜像 digest、git commit、parser stable/candidate 指针、导出时间
```

### A4. 打包与校验

```
feedback_bundle_YYYYMMDD_HHMM.tar.gz
  manifest.json      # 导出范围、条数、版本信息、生成人
  SHA256SUMS         # 包内逐文件
```

- 生成后计算整包 SHA256，写入交接单。
- 若含敏感标准原文，按单位要求做加密（密码走另一渠道）。

## 5. 阶段 B：离线传输

- 走单位审批的移动介质/单向导入设备；只传一个 `tar.gz` + 一张 sha256 值。
- 本地解压前先校验整包 sha256，再校验包内 `SHA256SUMS`。
- 记录交接单：文件名、大小、sha256、导出人/接收人、时间。

## 6. 阶段 C：本地复现基线

1. 本地 WSL 启动现有栈（镜像 `hanson-*-local`，模型指向 192.168.1.35）。
2. 导入文档：按 `manifest.json` 逐份上传到本地（按 sha256 去重），并记录「内网 document_id → 本地 document_id」映射。
3. 固定算法版本：把导出的 `parser_core/<version>` 发布为本地 stable，确保与内网完全一致。
4. 复跑并生成**基线报告**：
   - 每份文档的阶段耗时、记录数、复核发现
   - 台账逐条对照：`feedback_id → 当前输出 → 期望输出 → 结论（命中/未命中）`

> 基线未完全复现时，先排查环境差异（模型版本、OCR 参数、DPI），不要直接进入优化。

## 7. 阶段 D：本地优化与回归

1. 修改 `new_app/services/sandbox/runtime/*.py`（算法主体；必须保持 stdlib-only、Python 3.12）。
2. 发布候选：`--version 1.7.41 --channel candidate`。
3. 用台账样本 + 30 份标准回归集对比基线：
   - 台账条目命中率
   - 结构化记录数/分类分布的异常波动
   - 复核 error/warn 数量变化
4. 通过后本地 `promote stable`，产出回传包：

```
algo_update_1.7.41/
  parser_core/1.7.41/          # 资产文件 + manifest.json
  changes.md                   # 变更点、影响的规则、风险
  regression_report.md         # 台账逐条结论 + 回归对比
  SHA256SUMS
```

> 如果算法改动需要新增第三方依赖：现有资产机制不支持，必须重建 arm64 镜像并整包传输，属于高成本路径，能避则避。

## 8. 阶段 E：回传内网上线（201）

### E1. 备份（必做）

```bash
cd /home/htjiance8/hanson-deploy/deploy-package
tar czf backup/recipe_registry_$(date +%Y%m%d_%H%M).tar.gz data/recipe_registry
# 记录当前 stable 版本
curl -s http://127.0.0.1:18000/... | grep parser   # 或读 channels.json
```

### E2. 发布新资产（推荐走 API）

- 把回传包解压到 201 临时目录。
- 在 `hanson-new-app` 容器内执行发布脚本（读取文件 → `POST /internal/assets` → `promote stable`）：
  - 发布后资产目录落到 `data/recipe_registry/assets/parser/parser_core/1.7.41/`
  - `channels.json` 的 stable 指针切到 1.7.41
- **不需要重启任何容器**，下一次解析自动使用新版本。

### E3. 验收

1. 对台账涉及的 task 调用 `POST /api/v1/integration/retrigger` 复跑。
2. 逐条比对：台账描述的问题是否消失、记录数是否异常、复核警告是否增加。
3. 通过后在台账标记：`fixed`，并记录 `parser_version=1.7.41`、验证 `run_id`。

### E4. 回滚（秒级）

- 优先：调用 rollback/promote 把 stable 切回 `1.7.40`。
- 兜底：恢复 E1 备份的 `data/recipe_registry` 目录，重启 `recipe-registry` 容器。

## 9. 版本与兼容规则

| 规则 | 说明 |
|---|---|
| 版本号 | 递增三段式，禁止复用已发布版本号 |
| 资产内容 | 仅 `services/sandbox/runtime/` 下 9 个 py + `dictionary_data.json`；stdlib-only |
| 通道 | 本地先 `candidate` 验证，再 `stable`；内网只接收 `stable` 晋升 |
| 兼容 | `runtime_api=sandbox-engine/1`、`python=3.12` 必须与现场一致 |
| 审计 | `promote` 必须带 `actor` 与 `note`（关联台账批次号） |

## 10. 安全与合规

- 导出包含标准原文与业务数据：按单位要求审批；介质加密；密码单独传递。
- 只导出与台账相关的文档，不做全库导出。
- 回传包只含算法代码与报告，不含任何原文、记录或个人信息。
- 全程保留导出/导入清单与哈希，便于审计。

## 11. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 内网 stable 在优化期间被改动 | 本地基线与现场不一致 | 回传前核对 stable 版本；不一致先重新导出差异 |
| 台账涉及文档过多 | 导出包过大 | 按批次（如每次 10–20 条）分批闭环 |
| 算法需要新依赖 | 无法用资产热更 | 单独评估镜像重建与 arm64 离线传输 |
| 本地模型与现场版本不同 | 误判 | `versions.json` 固定模型名与地址；必要时现场取样对比 |
| 回传后指标变差 | 影响生产 | 先 candidate 复跑、再 stable；保留一键回滚 |

## 12. 待确认事项

1. 台账导出范围：按时间窗还是按状态？每批建议条数？
2. 文档包是否需要包含页面截图（PNG）？会增加体积但便于定位版面问题。
3. 离线介质与审批流程由谁负责？是否允许加密压缩包。
4. 验收标准：台账条目“全部命中”还是允许分批放行。
5. 是否需要在本地保留一套与 201 同版本的模型服务（当前用 192.168.1.35，模型版本可能与 202 不一致）。
