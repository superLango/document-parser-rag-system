# M8 业务词典导入与对账报告

> 日期：2026-11-12
> 源：`legacy/metal-doc-agent/configs/dictionaries/`（categories/items/methods）
> 目标：`new_app/services/orchestration/data/dictionary/business_dictionary.json`
> 原始数据：[M8-dictionary-import.json](M8-dictionary-import.json)
> 映射说明：[dictionary-mapping.md](../migration/dictionary-mapping.md)
> 结论：**对账通过**（唯一编码 2203/2203，状态无差异；1 处重复编码已合并并记录）

## 1. 条目数

| 类型 | 源 | 输出 | 差异 |
|---|---|---|---|
| category | 79 | 78 | -1（`CATEGORY:19` 重复合并） |
| item | 1045 | 1045 | 0 |
| method | 1080 | 1080 | 0 |
| 合计 | 2204 | 2203 | -1（重复编码合并） |
| 唯一编码 | 2203 | 2203 | 0 |

源文件 SHA256：

| 文件 | SHA256 |
|---|---|
| `categories.json` | `dbdfb931e6b4465c95306cdbc240174965f257419b9ae168e765ca2ca0d417db` |
| `items.json` | `ce1467eb41b5b70e0d1cee0aa4a8bc7fb07a58232c232bcfb4e5bcc19b18b195` |
| `methods.json` | `579d723569a97ea23108a1c90214b7d884da19e2d707ed98fb334e8547230489` |

## 2. 编码

- 源唯一编码：2203
- 输出编码：2203
- 缺失编码：0
- 多余编码：0
- 重复编码：`CATEGORY:19`（弯曲试验 / 弯曲）→ 保留“弯曲试验”，另一名称并入别名

## 3. 别名

- 输出别名总数：108
- 别名差异：1 处（`CATEGORY:19` 由 `["冷弯"]` 合并为 `["冷弯","弯曲"]`）
- 其余条目别名集合与源一致

## 4. 状态

| 状态 | 源 | 输出 |
|---|---|---|
| active | 2203 | 2202 |
| inactive | 1 | 1 |

状态差异：0。inactive 条目保留，不参与页面默认筛选时可选择“全部状态”。

## 5. 失败清单

无失败条目（0）。

## 6. 可重入与断点

- 重复执行导入：输出 SHA256 前后一致（`E822377360F89865280678D240CF0EA4E9FE2E66CA069BADABF3C78A81EC6863`）。
- 检查点：`M8-dictionary-import.checkpoint.json`（每个源文件处理完落盘；中断后重跑跳过已完成文件）。
- 原子写：`.tmp` + replace。

## 7. 结论

| 对账项 | 门槛 | 结果 |
|---|---|---|
| 条目数 | 100% 或差异有清单 | 通过（重复编码已列明） |
| 编码 | 100% 或差异有清单 | 通过（0 缺失/0 多余） |
| 别名 | 差异有清单 | 通过（1 处合并） |
| 状态 | 差异有清单 | 通过（0 差异） |
