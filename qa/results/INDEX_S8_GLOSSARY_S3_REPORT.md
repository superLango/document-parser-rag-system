# 专业术语集 S3 测试报告（M33-S3：术语条目 API）

- 日期：2026-08-12
- 关联实现：
  - `app/services/glossary/term_service.py`：术语 CRUD、过滤查询、审核、批量导入、CSV 导出、分类
  - `app/api/v1/endpoints/kb_glossary.py`（terms_router）：/kb/{kb_id}/terms 系列端点
  - `app/schemas/glossary.py`：TermCreate/Update/Review/Batch
- 端点：列表（术语集/分类/状态/关键词过滤）、分类、导出 CSV、详情、创建、批量导入（≤5000 幂等）、更新、审核（approve/reject）、删除

## 用例统计（S3 新增）

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_glossary_s3_unit.py` | 3 | 通过 |
| L1 补测 | `qa/unit/test_glossary_s3_coverage.py` | 6 | 通过 |
| L2/L3 功能 | `qa/integration/test_glossary_s3_api.py` | 2 | 通过 |
| L4 边界 | `qa/boundary/test_glossary_s3_boundary.py` | 4 | 通过 |
| L5 安全 | `qa/security/test_glossary_s3_security.py` | 4 | 通过 |
| **S3 小计** | | **19** | **19 通过** |

## 整体（S1-S3）统计

- 全量回归：**62/62 通过**
- 服务层行覆盖率：**96%**（security 96 / source_api 95 / source_db 95 / loader 98 / term_base_service 93 / term_service 99）
- ruff 全部通过

## 关键覆盖点

1. 过滤：术语集/分类/状态/关键词（term_name/standard_name/english_term）；
2. 创建校验：空名/超长/未知术语集/同术语集重名 409；
3. 批量导入：≤5000、批内同名去重（S2 修复延续）、幂等重跑不新增、并发导入最终无重复；
4. 审核：approve→active / reject→rejected / 非法动作 400；reviewer 落库；
5. 导出：UTF-8 BOM + 表头 + 同义词/别名 | 分隔 + 空库仅表头；
6. 权限：viewer 只读、editor 可写、非成员 403、跨 KB 隔离（详情/列表/创建全链路）；
7. 删除软删（详情 404）。

## 结论

S3 通过铁律验收：19/19（S1-S3 合计 62/62），覆盖率 96%。
