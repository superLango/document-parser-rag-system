# 专业术语集 S1 测试报告（M33-S1：数据库与模型）

- 日期：2026-08-12
- 关联实现：
  - `backend/alembic/versions/010_term_glossary.py`：term_bases / terms 两表 + 部分唯一索引 + RLS（8 策略）
  - `backend/app/models/glossary.py`：TermBase / Term + 常量
  - `backend/app/models/__init__.py`：模型注册
- 开发库与测试库均已升级至 010_term_glossary

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_glossary_models.py` | 5 | 通过 |
| L2 集成 | `qa/integration/test_glossary_storage.py` | 2 | 通过 |
| L4 边界 | `qa/boundary/test_glossary_storage_boundary.py` | 3 | 通过 |
| L5 安全 | `qa/security/test_glossary_storage_security.py` | 4 | 通过 |
| **合计** | | **14** | **14 通过 / 0 失败** |

行覆盖率（coverage sysmon）：`app/models/glossary.py` 58 语句 0 未覆盖，**100%**。

## 关键覆盖点

1. TermBase/Term 字段、默认值与常量（source_type/status）；
2. 部分唯一索引：软删后允许重建同名（term_bases/terms），未删重名被拒；
3. 跨 KB 同名术语集互不冲突（唯一索引含 kb_id）；
4. RLS：无上下文拒绝、viewer 只读、editor 可写、跨 KB 隔离（8 条策略）；
5. ORM 软删语义与重建。

## 迁移代码审查（硬性规则首轮执行）

- 已清理测试中的无用残留（boundary 中 `if False else None` noop）；
- security 测试由共享 db_session 改为独立 session 模式（消除连接池 MissingGreenlet 与状态污染）；
- 原项目无用能力未迁移（standardize_text/术语合并/旧 terms.py 兼容端点/暗色配色）；
- 审查清单：无调试残留、无未使用 import、无死分支、ruff 通过。

## 结论

S1 通过铁律验收：五层全覆盖（L1/L2/L4/L5，本阶段无独立 L3 前端场景），行覆盖率 100%。
