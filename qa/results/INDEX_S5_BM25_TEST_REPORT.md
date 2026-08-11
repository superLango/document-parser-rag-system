# S5 jieba BM25 测试报告（M29/D4）

- 日期：2026-08-12
- 关联实现：`backend/app/services/indexing/bm25.py`、`backend/app/core/config.py`（BM25_K1/BM25_B）、
  `backend/app/services/document_service.py`（run_index_task/delete_document 集成统计）
- 设计：jieba + ASCII 词元（元素符号/标准号/数值范围）；PG `kb_bm25_stats` 增量统计
  （n_docs/total_len/doc_freq，version 乐观递增 + 行锁）；查询候选经 `bm25_tokens ?|` GIN 过滤后 Python 打分

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_bm25_unit.py` | 6 | 通过 |
| L2 集成 | `qa/integration/test_bm25_integration.py` | 1（索引→统计→打分排序） | 通过 |
| L3 功能 | `qa/integration/test_bm25_integration.py` | 2（重索引统计稳定/删除回退） | 通过 |
| L4 边界 | `qa/boundary/test_bm25_boundary.py` | 6（空语料/未知 KB/超长查询/无匹配/钳制/空查询） | 通过 |
| L5 安全/并发 | `qa/security/test_bm25_concurrency.py` | 2（6 并发统计一致/KB 隔离） | 通过 |
| **合计** | | **17** | **17 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M29 jieba BM25 | 6 | 1 | 2 | 6 | 2 | 17 | 是（5/5 层） |

行覆盖率（coverage sysmon）：`bm25.py` 116 语句 0 未覆盖，**100%**。

## 关键覆盖点

1. 分词：GB/T 标准号、元素符号（C/Cr）、数值范围（0.015~0.060）、中文 jieba、标点/符号过滤；
2. BM25 公式：idf 惩罚高频、词频增益、avg_dl<=0 防御；
3. 索引集成：分块后计算 bm25_tokens 落库，同事务增量更新 stats；
4. 重索引幂等：先回退旧统计再增新统计，n_docs/total_len 不漂移；
5. 删除回退：软删文档同时硬删块并回退统计；
6. 查询打分：GIN 候选过滤 + Python 打分排序，相关块命中正确；
7. 边界：空语料/未知 KB/空查询/纯标点/无匹配/超长查询/回退钳制；
8. 并发：同一 KB 6 并发新增统计最终一致（ON CONFLICT + 行锁）；
9. KB 隔离：不同 KB 统计互不干扰。

## 测试中修复的缺陷

1. jieba 标点产出为词元 → 过滤纯标点/符号；
2. 统计行并发创建竞态（UniqueViolation）→ INSERT ON CONFLICT DO NOTHING + FOR UPDATE；
3. SQL JSONB 内嵌双引号破坏字符串 → 转义；
4. 分块 fixture 多文本合并单块 → 独立章节构造多块。

## 回归

- M28（S4 索引任务）集成回归 3/3 通过；M28 快速用例 13/13 通过；
- ruff 全部通过。

## 结论

S5 通过铁律验收：五层全覆盖（17/17），行覆盖率 100%，并发一致性与删除回退验证通过。
