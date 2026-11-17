# 解析算法升级与回归报告（2026-11-17）

> 数据来源：`标准拆分提取-20261117-094032`（198 份生产解析结果 + 原文 PDF + OCR md）
> 约束：本地无法连接模型，回放基于生产导出的 md 表格，不重跑 OCR。

## 1. 问题定位

对 198 份文档做「生产结果 vs md 表格」对照，确认三类系统性漏抽：

| 问题 | 典型文档 | 表现 |
|---|---|---|
| 混合性能表被单一配方独占 | 84（1.4418 锻件） | 表头含 Rm/Rp0.2/A/AKv/HB 五列，只抽出 HB，其余 4 列判 `MEASURE_COLUMN_MISSING` |
| 无牌号“要求表”处理错误 | 84、83、85 等 | 表头即性能项、只有 1 行数值；首个数值被当牌号，其余列丢弃 |
| 性能列被误判为条件列 | 含“室温冲击AKv”“硬度HB”的表 | 列被条件占用，导致对应 measure 无法绑定 |

另有非算法因素：部分文档的要求数值来自被引用标准（如 Q/S19.4019），正文只有“应符合表 X”，这类缺失无法从本文抽取；部分 OCR 把版面压平成单列表格。

## 2. 代码改动

1. **路由：混合性能表交给覆盖全部列的配方**
   [matcher.py](file:///f:/hanson/hanson_doc_parse/new_app/services/recipe_registry/matcher.py#L149-L223)
   - 表头同时出现硬度与拉伸/冲击 measure 时，排除“仅硬度”配方；
   - 机械配方已绑定 HB/HBW/HRC/HV 与 KV2/KU2，因此五列可一次抽全；
   - 纯硬度表（只含 HB/HRC…）不受影响。

2. **无牌号要求表识别**
   [builtin.py](file:///f:/hanson/hanson_doc_parse/new_app/services/sandbox/runtime/builtin.py#L4360-L4370)
   - 条件：无行键、无自动条件列、≥2 个 measure 列、数据行 ≤2；
   - 产出 `grade=全部牌号` 的单条多属性记录，不再把首个数值当牌号。

3. **性能列优先于条件列 + 中文紧贴符号匹配**
   [builtin.py](file:///f:/hanson/hanson_doc_parse/new_app/services/sandbox/runtime/builtin.py#L2951-L2982)
   - 新增 `_header_binds_measure`，无牌号表分类条件前先判断是否为性能列；
   - `_alias_matches` 增加 ASCII 词边界匹配，`室温冲击AKv` 可绑定 KV2，`hb` 不会误中 `hbw`。

## 3. 全量 A/B 回归（198 份，同 harness）

回放方法：md 中的 `<table>` → `table_grid.parse_table` → 稳定通道配方匹配 → sandbox `parse_table` → 文档级投影。每份文档独立清理表格指纹，避免跨文档串扰。

| 指标 | 改动前 | 改动后 | 变化 |
|---|---|---|---|
| 属性总数 | 10,045 | 10,220 | **+175（+1.74%）** |
| 提升文档 | — | 22 | |
| 下降文档 | — | 6 | |
| 持平文档 | — | 170 | |

按类别：

| 类别 | 变化 |
|---|---|
| 室温拉伸 | +96 |
| 冲击试验 | +47 |
| 高温拉伸 | +31 |
| 化学成分 | +23 |
| 硬度试验 | +3 |

代表文档：

| 文档 | 改动前 | 改动后 |
|---|---|---|
| 84 | 仅 HB（1 属性） | Rm/Rp0.2/A/KV2/HB（5 属性） |
| 83 | 硬度 1 + 化学 1 | 拉伸 3 + 硬度 1 + 冲击 1 + 化学 2 |
| 85 | 6 属性 | 25 属性 |
| 7 | 994 属性 | 1,034 属性 |
| 210 | 726 属性 | 763 属性 |

### 下降文档说明

- 28、62 是同一份文档的两个副本：原先把温度 650/700 当牌号，定性条目按“牌号”重复生成；现在归并为 `全部牌号`，属性数下降属于**去重**，不是数据丢失。
- 125、16、130、162 各 -1 ~ -3，均为同类归并/去重，未发现真实字段丢失。
- 28/62 的高温拉伸条件串仍有拼接现象（如 `650≥600280≥30>τ`），属历史 fallback 行为，列入后续优化。

## 4. 已知未覆盖项

1. **引用标准型文档**：正文只写“化学成分/力学性能应符合 Q/S… 表 X”，数值在另一份标准中，本文无法抽取；需依赖跨标准库或人工补录。
2. **OCR 压平表格**：整段文字被识别成单列表格（如 155 的 101 行单列），无列结构可绑定。
3. **生产中的 Agent 路由**：部分表在生产由 RouterAgent（Qwen）兜底路由，本地无模型时无法复现，回放里表现为未匹配；上线后仍有 Agent 兜底，不影响现场行为。
4. **条件串拼接**：多行表头/合并单元格场景下，条件值可能被拼成整行文本，待后续单独修复。

## 5. 上线步骤（201 内网）

1. 构建 arm64 应用镜像（已包含 matcher 与 runtime 改动）：
   `bash deploy-package/scripts/build-arm64-images.sh`
2. 传输并加载：
   ```bash
   docker load -i images/hanson-runtime-images-arm64.tar
   cd /home/htjiance8/hanson-deploy/deploy-package
   docker compose up -d
   ```
3. 发布新解析资产（启用 runtime 改动，无需重启）：
   ```bash
   docker compose exec app python scripts/assets/publish_parser_asset.py \
     --api http://recipe-registry:8005 --version 1.7.41 --channel candidate \
     --actor release --note "mixed-table + no-key requirement table"
   # 用台账样本 retrigger 验证通过后
   docker compose exec app python scripts/assets/publish_parser_asset.py \
     --api http://recipe-registry:8005 --version 1.7.41 --channel stable \
     --actor release --note "promote after regression"
   ```
4. 回滚：`promote` 回 1.7.40，或恢复 `data/recipe_registry` 备份。

## 6. 复现方式

- 全量回放：`deploy-package/scripts/run-replay-all-amd64.sh`
- A/B 对比：`replay-all-baseline.json` vs `replay-all-opt.json`
- 单表明细：`run-debug-table.sh <folder> <table-index>`
