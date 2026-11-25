# app_v3 S1 阶段报告（Schema / 归一化 / 基准数据）

> 阶段：P0-S1（第 1 周）  
> 日期：2026-11-25  
> 状态：**S1 核心交付完成**（Schema + 归一化 + 基准数据 + 诊断/测试）  
> 约束：未修改冻结版 v2 代码；仅新增 `app_v3/`。

## 1. 目标与完成情况

| 目标 | 交付 | 状态 |
|---|---|---|
| 规范记录 Schema v1 | `schema/record.v1.schema.json` | ✅ |
| 条件/单位规范 | `schema/conditions.v1.json`、`schema/units.v1.json` | ✅ |
| 类别/项目本体 | `schema/ontology.v1.json`（76 类 / 1070 项 / 1158 方法） | ✅ |
| 中英项目词表 | `normalize/items.cn_en.json` | ✅ |
| 牌号解析 | `normalize/grade.py`（中英/多牌号/纯字母/表头短语拒绝） | ✅ |
| 条件归一化 | `normalize/conditions.py`（状态/方向/温度/尺寸/单位） | ✅ |
| 文档内别名 | `normalize/aliases.py`（名称(代号)挖掘） | ✅ |
| 记录归一化流水线 | `normalize/pipeline.py` + CLI | ✅ |
| 诊断/报告 | `normalize/report.py`、`eval/s1-normalization-report.json` | ✅ |
| 基准数据 | `benchmark/`（26 份 PDF + 26 份 gold + manifest） | ✅ |
| 单元测试 | `tests/` | ✅ 24 passed |

## 2. 代码与数据结构

```
app_v3/
├── schema/
│   ├── record.v1.schema.json        # canonical record（JSON Schema）
│   ├── conditions.v1.json           # 条件维度定义
│   ├── units.v1.json                # 单位别名
│   └── ontology.v1.json             # 类别/项目本体（来自汉唐 taxonomy）
├── normalize/
│   ├── items.cn_en.json             # 项目/度量中英词表
│   ├── items.py                     # 项目名归一化
│   ├── grade.py                     # 牌号解析/拆分/别名
│   ├── conditions.py                # 条件/单位归一化
│   ├── aliases.py                   # 文档内状态别名挖掘
│   ├── pipeline.py                  # 归一化流水线 + CLI + summary
│   └── report.py                    # 报告输出
├── benchmark/                       # 26 份基准文档 + gold + manifest
├── eval/                            # v2 基线快照 + S1 归一化统计
├── scripts/s1_demo.py               # 对 20 份 v2 产物做归一化演示
└── tests/                           # 24 个单元测试
```

### 2.1 归一化流水线用法

```bash
python -m app_v3.normalize.pipeline \
  --input .tmp/batch20/<doc>/extract/assembled/assembly-report.json \
  --output app_v3/eval/<doc>-normalized.json \
  --ocr .tmp/batch20/<doc>/ocr/ocr.json
```

输出：
```json
{
  "schema_version": "normalized.v1",
  "aliases": {"M": "软态(M)"},
  "summary": {"total": 202, "status": {"ok": 190, "warn": 12, "unresolved": 0}},
  "records": [
    {
      "record_id": "...",
      "schema_version": "record.v1",
      "category": "室温拉伸",
      "item": "抗拉强度(Rm)",
      "grade": "N4",
      "grade_aliases": ["N5"],
      "requirement": "≥345",
      "operator": "≥",
      "unit": "MPa",
      "conditions": {"试验温度": "室温", "试样状态": "软态(M)", "尺寸厚度": "0.1~1.5mm"},
      "evidence": {"source": "table", "table_id": "T9", "page_no": 9},
      "status": "ok",
      "diagnostics": []
    }
  ]
}
```

## 3. S1 归一化演示结果

对 20 份 v2 产物（`.tmp/batch20/*/extract/assembled/assembly-report.json`）执行归一化：

| 指标 | 数值 |
|---|---:|
| 文档数 | 20 |
| 记录数 | 9185 |
| status=ok | 7862 |
| status=warn | 1323 |
| status=unresolved | 0 |
| 牌号解析率 | 7867 / 9185 = **0.8565** |
| grade_rejected | **1319** |
| missing_grade | 4 |

说明：
- `grade_rejected` 高，主要因为 **v2 上游把化学元素/英文单词放进了 grade 字段**（如 AMS 的 `Aluminum`、`Vanadium`），S1 已能**识别并标记**，不再静默当牌号；
- 说明仅靠归一化不能修复上游绑定错误，需要 S2 的"牌号列识别/绑定修正"；
- 全部 `unresolved=0`，因为 S1 对缺证据/缺牌号采用 warn（S2 验证器会升级为 unresolved 规则）。

示例：
```json
{"doc":"ams-4928x","raw_grade":"Aluminum","item":"断后伸长率(A)","requirement":"≤5.50"}
{"doc":"ams-4928x","raw_grade":"Vanadium","item":"断后伸长率(A)","requirement":"≤3.50"}
```

## 4. 单元测试

```bash
python -m pytest app_v3/tests -q
# 24 passed
```

覆盖：
- 中/英文牌号列识别；
- 多牌号拆分（含 `NW4-0.07`、`DN`）；
- 拒绝表头短语（`Up to 2.000,incl(1)`、`Sheet and strip`）；
- 状态代号/状态全称、方向中英、温度/尺寸/单位归一；
- 文档内别名清洗（`及半硬态(Y2)`、`状态为软态(M)`）；
- 归一化记录、英文项目名、化学元素不误配；
- 缺失字段/grade 拒绝诊断。

## 5. 基准数据（26 份）

| 项 | 数值 |
|---|---:|
| 文档 PDF | 26 |
| gold JSON | 26 |
| PDF 体积 | 43.3 MB（本地备份，默认不入 git） |
| gold 体积 | 10.3 MB（入库） |
| manifest | `benchmark/manifest.json`（含 SHA256 + v2 历史基线） |

来源：
- 20 份：`E:\Desktop\标准抽取20份`
- 6 份：gbt-713.7-2023、gbt-1591-2018、gbt-3191-1998、gbt-6892-2015、gjb-2294-1995、yst-397-2015

## 6. 已知限制（S2 处理）

1. **上游绑定错误**：牌号/项目被错填（AMS 化学元素当 grade）——需要 S2 牌号列识别 + 绑定校验；
2. **验证器未完整**：证据/值守恒/条件完整性/冲突检测尚未接入（S1 只有基础诊断）；
3. **未解决队列未落盘**：S1 仅 status/diagnostics，S2 加队列与原因码；
4. **评测脚本尚未固化**：当前用 `.tmp` 中的临时对照；S2 迁入 `app_v3/eval/run_eval.py`；
5. **本体词表需扩充**：英文项目/单位/状态覆盖还需按盲测补充（不能按金标反推）。

## 7. 下一步（S2）

- WP0.4 验证器（证据/守恒/条件完整性/冲突/未解决队列）；
- 牌号列识别与上游绑定修正（S1 grade 拒绝的直接原因）；
- 固定评测脚本与盲测集；
- P0 验收：一致率 ≥0.90、覆盖率 ≥70%、多余 <1000、未解决 ≤10%。
