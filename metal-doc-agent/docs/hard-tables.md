# 困难表清单（M1-S3）

> 更新：2026-10-26
> 关联：`stages/01-M1-单文档MVP.md` M1-S3
> 目的：记录 TableGrid v1 已处理/未处理的复杂表，避免“静默失败”。

## 1. 状态图例

| 状态 | 含义 |
|---|---|
| pass | 当前可正确解析并被抽取消费 |
| partial | 结构已识别，但字段/列拆分仍需后续处理 |
| skip | 当前主动跳过，不进入抽取 |
| pending | 尚未处理 |

## 2. 清单

| 文档 | 表 | 问题 | 当前状态 | 证据/结果 | 后续 |
|---|---|---|---|---|---|
| GB/T 1591-2018 | 表1 热轧钢的牌号及化学成分 | 表头 `rowspan=5 colspan=13` 溢出到数据行；C 按厚度拆子列；`colspan=14` 少一列 | pass | `runs/m1s7grid/gbt1591_2018`：T1 重建为 17 列，C 在 col2/col3，Si…B 在 col4…16；`gold verify` 通过 | 保持回归 |
| GB/T 40303-2021 | 表2 化学成分（T3） | 3 个“级别”块、27 元素、OCR 跨页 | pass | `runs/s3_gh3`：T3 blocks=7，caption=表2 化学成分 | 保持回归 |
| GB/T 40303-2021 | 表3 力学性能（T4） | 行列错位/多条件 | pass | `configs/table_repairs.json` 修复 `>80~125`、`>125~200` 两组的交货状态/列序；Qwen 抽出 10 条 T4 记录，条件含 `热轧棒材 / >80~125 / 横向` | 保持 fixture |
| GB/T 40303-2021 | 表3 力学性能（续）（T6） | 同页续表；第 6-7 行缺“级别/公称直径” | partial | fixture 补齐 `高级优质级 / 200~300` 两行，修复 `-196` 与表头列序；T6 的 `Rp0.5`/`KU2` 与 T4 的 `Rp0.2`/`KUJ` 不同，主动保持独立表，避免串列 | 保持独立表 |
| GB/T 40303-2021 | T5 | OCR 把表注包成 1 列 `<table>` | skip | profile=unknown，4×1 | 识别为 footnote，不进入抽取 |
| GB/T 40303-2021 | 表6 检验项目（T9/T10） | 跨页续表 | pass | merged_pages=[12,13]，T9/T10 合并 | 保持回归 |
| GB/T 40303-2021 | 表B.3 力学性能（T14/T15） | 两页列数 15 vs 12；表头 rowspan 泄漏到数据行 | pass | fixture 将 T14 重建为 11 列、补齐 A 行，T15 去尾列；修复后继续合并为 T14，`merged_pages=[17,18]`，共 15 行（A-G + 表注） | 保持 fixture |
| JX-25-035 | 表1 GH4698 化学 | 转置表（元素为行） | pass | `inspect`：T1 orientation=element_rows，profile=chemical_composition；condition=`wt% / 化学成分` | 保持回归 |
| JX-25-035 | T6 | caption 缺失、15×4 | pass | fixture caption=`附录A 化学成分试验标准`；表型 unknown，不进入记录抽取 | 保持 fixture |
| GJB 3325A-2019 | 表1 牌号及化学成分 | 数据行（`30Si2MnCrMoVE`）被误判为范围表头，只抽出 1 个牌号 | pass | 修正牌号识别后 header_rows=2，3 个牌号全部抽出；condition=`熔炼分析` | 保持回归 |
| GJB 2294A-2014 | 表1 化学成分 | `类型` 列未作为 condition，记录键为空 | pass | condition=`奥氏体型`；5 条黄金集记录可匹配 | 保持回归 |
| GB/T 3191-1998 | 表6/表7 棒材室温纵向力学性能（T6/T7） | T6 的 2A11/2A12 行多出直径单元格；T7 的 6061 行状态/直径错位，伸长率被读成 215/255/260 | pass | `configs/table_repairs.json` 修复 T6 5 行、T7 2 行；2A11 `A=12`、6061 `A=9`；L2 清零，状态 review | 保持 fixture |
| GB/T 1220-2007 | 表7 力学性能 | 原始表头缺少 `断面收缩率Z/%`，TableGrid 把 Z 列标成“硬度b 不大于” | pass | fixture 恢复表头 `断面收缩率Zc/%`；`header_paths[7]=断面收缩率Zc/% / 不小于`，硬度列后移 | 保持 fixture |
| Q-Du 302-2015 | 表2 室温力学性能 | 多行表头、方向条件 | pass | 真实 OCR（`runs/m1s3_qdu_p5`）：1 表、3 记录、15 证据 | 保持回归 |

> GB/T 1591 表1 的列定义已统一为 17 列（col0 钢级、col1 质量等级、col2 C≤40h、col3 C>40、col4 Si … col16 B）。TableGrid 现在把表头与数据区分开重建：表头 rowspan 不再写入数据行；单值 C（`rowspan>1`、无 `colspan`）复制到两个厚度子列；`>40` 子表头从溢出列回填到 col3。黄金集证据列也已同步，`gold verify` 1595 条全部通过。
>
> 评测记录匹配：grade 相同时，两侧 condition token 集合互为子集（交集非空）即视为兼容；报告用 `Condition relaxed` 单独计数。这解决了黄金集自由文本 condition 包含 `方向未规定`、`室温` 等可选信息导致的假阴性。

## 3. 本轮已实现的规则

1. **跨页 caption**：上一页末尾的 `表N ...` 可被下一页表继承；只有列数/表头相似时才继承，避免把化学表 caption 误挂到力学表。
2. **表后 caption**：表后 400 字符内、下一张表之前的 `表N ...` 可作为 caption。
3. **续表合并**：相邻页、同表号、同列数、表头相似时合并；保留 `merged_pages` 与 `continuation_of`。
4. **表头判定**：首列 header 标记 + 范围子表头（`≤40`、`>40`、`不大于`）+ 索引数据行，避免把数据当表头。
5. **转置方向**：首列多数为元素符号时标记 `element_rows`；转置化学表归类 `chemical_composition`。
6. **脚注**：表内 `注` 行、`sup`、表后 `注：...` 均进入 `footnotes`。
7. **画像顺序**：检验项目优先于“取样方向/硬度”等单字段，避免把力学表误判为检验表。
8. **宽行脚注**：8 列以上、同一段 ≥20 字文本占非空单元格 ≥75% 的行，识别为表注并跳过抽取；修复 GJB 2294A 检验表、GB/T 40303 T6/T15 等把表注当数据行的问题。
9. **困难表 fixture**：`configs/table_repairs.json` 按标准化标准号（如 `GBT403032021`）登记表级修复；支持替换行、`<prev>` 继承上一行、列交换、单元格补丁、删除空行、复制表头、去尾列。pipeline 在抽取前应用，数值均按原 PDF 核对。

## 4. 回归命令

```powershell
python -m unittest discover -s tests -v
python -m metal_doc_agent.cli run "..\标准文件\GBT 40303-2021\GBT 40303-2021   GH4169合金棒材通用技术条件.md" --out runs\s3_gh --ocr mock --extractor mock
python -m metal_doc_agent.cli run "..\标准文件\GBT 1591-2018\GBT 1591-2018 低合金高强度结构钢.md" --out runs\s3_1591 --ocr mock --extractor mock
python -m metal_doc_agent.cli inspect "..\标准文件\JX-25-035\JX-25-035+GH4698高温合金棒材采购技术协议.md"
```

当前回归结果：

- GB/T 40303：17 表、11 记录、116 证据、`pass`；
- Q-Du 302：5 表、3 记录、15 证据；mock `review`，Qwen 抽取 `pass`；
- GB/T 1591：16 表、24 记录、534 证据、`pass`；
- JX-25-035 T1：`element_rows` + `chemical_composition`；
- 当前全量 120 个测试通过（新增 T1 表头溢出、牌号识别、条件兼容、属性别名、KIC 单位、牌号简写展开、宽行脚注、困难表 fixture、降序区间回归）。
- 宽行脚注规则上线后，`runs/m1_qwen_ws2` 的 G1 指标保持不变：Record F1 0.8823、Field F1 0.8176、Value 0.9263、Evidence 1.0；GJB 2294A 检验项 17→16，GB/T 1220 分类项 160→158（均为误收表注行被剔除）。
- 修复后单文档验证：`runs/m1.5_qwen/gbt40303_2021`，16 表、30 记录、367 证据、`review`；T4 10 条、T6 5 条、T14 11 条（A-G，含原 T15 行）；Record F1 1.0、Field F1 0.9262、Value 1.0、Evidence 1.0。
- 全量验证：`runs/m1.5_qwen` 20 份，`accept --strict` 结论 **GO**；Record 0.8733、Field 0.8279、Value 0.9316、Evidence 1.0、Coverage 0.85、p95 193.4s。相对 qwen-s8：Field +0.0103、Value +0.0053、Record -0.009（回归阈值内）。

## 5. 后续优先级

1. 表画像准确率统计与回归样本扩充；
2. T5 类“注表”识别为 footnote（宽行脚注已覆盖大部分）；
3. 将表行/列修复推广到仍 L2 audit fail 的 6 份文档（GB/T 1220、33084、3203、6892、GJB 2294A、5301）；
4. 为 fixture 增加按 caption/表头签名的匹配，降低 table_id 漂移风险。
