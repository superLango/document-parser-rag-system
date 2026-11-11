# 业务词典映射说明

> 日期：2026-11-12
> 对应里程碑：M8-01
> 源：`legacy/metal-doc-agent/configs/dictionaries/`
> 目标：`new_app/services/orchestration/data/dictionary/business_dictionary.json`

## 1. 源文件

| 文件 | 条目 | SHA256 | 说明 |
|---|---|---|---|
| `categories.json` | 79 | `dbdfb931…d417db` | 项目大类 |
| `items.json` | 1045 | `ce1467eb…b18b195` | 检测项目 |
| `methods.json` | 1080 | `579d7235…7230489` | 试验方法 |
| 合计 | 2204 | — | 唯一编码 2203（`CATEGORY:19` 重复） |

`business_dictionary.hanson.json`（2204 条）为同源合并快照，可用于交叉校验；`business_dictionary.json`（95 条）是 M7 页面使用的精简快照，M8 导入后由全量数据替换。

## 2. 字段映射

| 旧字段 | 新字段 | 规则 |
|---|---|---|
| `business_code` | `business_code` | 必填；全局唯一；重复编码合并并记录冲突 |
| `business_name` | `business_name` | 必填；首尾空白清理 |
| `type` | `type` | `category` / `item` / `method`，其他值进失败清单 |
| `family` | `family` | 空字符串归一为 `null` |
| `facets` | `facets` | 非对象归一为 `{}` |
| `aliases` | `aliases` | 去空、去重、去除与名称相同的别名 |
| `standard_no` | `standard_no` | 空字符串归一为 `null` |
| `category_code` / `category_name` | 同名 | 项目到分类的引用 |
| `status` | `status` | 默认 `active`；仅允许 `active` / `inactive` |
| `version` | `version` | 源快照版本；输出顶层保留 `hanson-ht-64c316a7` |

## 3. 冲突处理

| 冲突 | 处理 |
|---|---|
| 同一 `business_code` 同名同类型 | 合并别名与空字段，保留首条 |
| 同一 `business_code` 不同名称 | 保留首条，另一名称加入别名，记录 `DUPLICATE_CODE_MERGED` |
| 同一编码不同类型 | 跳过后者，记录 `CODE_TYPE_CONFLICT` |
| 空编码/空名称/非法类型 | 跳过并记录失败清单，不阻断其余条目 |

本期实际冲突：`CATEGORY:19`（弯曲试验 / 弯曲）→ 保留“弯曲试验”，别名合并为 `["冷弯","弯曲"]`。

## 4. 导入流程

```bash
cd new_app
python scripts/import_dictionary/import_dictionary.py            # 导入
python scripts/import_dictionary/import_dictionary.py --check    # 只校验不写
python scripts/import_dictionary/import_dictionary.py --force    # 忽略检查点重跑
```

- 可重入：相同输入重复执行输出字节一致（SHA256 校验）。
- 断点续跑：每个源文件处理完写入 `docs/reports/M8-dictionary-import.checkpoint.json`；中断后重跑跳过已完成文件。
- 原子写：先写 `.tmp` 再替换，避免半成品。
- 报告：`docs/reports/M8-dictionary-import.json`；同时生成同目录 `manifest.json`（输出校验和与统计）。

## 5. 输出结构

```json
{
  "schema_version": "2.0",
  "version": "hanson-ht-64c316a7",
  "source": "legacy:metal-doc-agent/configs/dictionaries",
  "source_files": ["categories.json", "items.json", "methods.json"],
  "stats": {"entries": 2203, "categories": 78, "items": 1045, "methods": 1080, "aliases": 108, "active": 2202, "inactive": 1},
  "entries": [
    {
      "business_code": "CATEGORY:27",
      "business_name": "化学成分",
      "type": "category",
      "family": "chemical_composition",
      "facets": {},
      "aliases": ["化学分析"],
      "standard_no": null,
      "category_code": null,
      "category_name": null,
      "status": "active",
      "version": "hanson-ht-64c316a7",
      "source_file": "categories.json"
    }
  ]
}
```

## 6. 回滚

1. `git checkout -- new_app/services/orchestration/data/dictionary/` 恢复上一版数据；
2. 或从 `data/dictionary/manifest.json` 记录的上一个 SHA256 对应的备份恢复；
3. 重启 orchestration（或等待 API 下次读取），词典页即回退。

词典导入不修改旧系统数据，回滚不影响解析链路。
