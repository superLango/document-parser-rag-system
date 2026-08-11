# S2 分块器与表格增强测试报告（M25/M27）

- 日期：2026-08-11
- 关联实现：`app/services/indexing/{models,chunker,table_cleaner,table_enhancer}.py`
- 数据契约：layout.json v1.2（document_tree + pages.blocks）
- 执行：`pytest unit/test_indexing_chunker_unit.py unit/test_table_enhancer_unit.py unit/test_indexing_coverage_supplement.py integration/test_indexing_chunker_integration.py boundary/test_indexing_chunker_boundary.py security/test_indexing_chunker_security.py`

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元（M25） | `qa/unit/test_indexing_chunker_unit.py` | 11 | 通过 |
| L1 单元（M27） | `qa/unit/test_table_enhancer_unit.py` | 10 | 通过 |
| L1 补测（分支覆盖） | `qa/unit/test_indexing_coverage_supplement.py` | 19 | 通过 |
| L2/L3 集成 | `qa/integration/test_indexing_chunker_integration.py` | 5 | 通过 |
| L4 边界 | `qa/boundary/test_indexing_chunker_boundary.py` | 7 | 通过 |
| L5 安全 | `qa/security/test_indexing_chunker_security.py` | 5 | 通过 |
| **合计** | | **56** | **56 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M25 层级父子分块器 | 11 | 3 | 1 | 4 | 3 | 22 | 是（5/5 层） |
| M27 表格增强 | 10 | 1 | 0 | 2 | 2 | 15 | 是（5/5 层） |
| 分支补测 | 19 | 0 | 0 | 0 | 0 | 19 | — |

行覆盖率（coverage sysmon 核心）：
- `chunker.py`：254 语句，0 未覆盖，**100%**
- `models.py`：40 语句，0 未覆盖，**100%**
- `table_cleaner.py`：105 语句，0 未覆盖，**100%**
- `table_enhancer.py`：89 语句，0 未覆盖，**100%**
- **合计 100%**

## 关键覆盖点

1. 层级面包屑（title 栈式维护）、父块 title/level/source_pages 推导、chunk_id 格式；
2. 表格独立成块不切分，增强文本只进 `content_for_embedding`，原始 HTML 保留在 `content`；
3. 题注整体前置（编号不重复）；文本句子边界切分、overlap（200 字符/2 句）；
4. 超长无边界文本弱边界优先 + 阈值硬切（有界性安全）；
5. 无 document_tree 降级路径、深度上限截断、未知块类型安全跳过；
6. rowspan/colspan 规整矩阵（占用登记按行，普通单元格不误判）；
7. 符号规范化、空行移除、数值列统计、表格类型识别；
8. 恶意输入：超深嵌套、超大 content、HTML 注入题注（作为数据保留）、路径字段不参与 IO；
9. 安全：不可信 layout.json 不崩溃、不栈溢出、块内容有界。

## 工程校验

- `ruff check app/services/indexing/`：通过
- `mypy`：通过（无错误输出）
- 测试中发现的缺陷已修复：rowspan 占用误伤、题注编号重复、超长段无界、overlap 提取越界与截断缺陷、硬切阈值未传实例值。

## 结论

S2 通过铁律验收：五层全覆盖（56/56），行覆盖率 100%，安全与边界场景验证通过。
