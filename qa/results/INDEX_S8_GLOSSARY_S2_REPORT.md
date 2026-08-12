# 专业术语集 S2 测试报告（M33-S2：术语集 API + 外部源 + 定时同步）

- 日期：2026-08-12
- 关联实现：
  - `app/services/glossary/security.py`：SSRF 防护（禁回环/链路本地/元数据，允许内网）+ 凭据加密/解密/掩码
  - `app/services/glossary/source_api.py` / `source_db.py`：API/DB 数据源客户端（超时/大小限制/JSON 路径/表与 SQL 模式）
  - `app/services/glossary/term_base_service.py`：CRUD、外部源测试/预览/同步、导入（批内去重幂等）、cron 扫描
  - `app/services/glossary/term_base_loader.py`：最小读取接口（C6 预留登记，分组+缓存）
  - `app/api/v1/endpoints/kb_glossary.py`：术语集端点（CRUD/test-api/test-db/db-tables/preview-sql/sync）
  - `app/schemas/glossary.py`、`app/tasks/arq_worker.py`（sync_term_bases_cron，小时可配置）

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_glossary_s2_unit.py` | 8 | 通过 |
| L1 补测 | `qa/unit/test_glossary_s2_coverage.py` | 9 | 通过 |
| L2 集成 | `qa/integration/test_glossary_api.py` | 3 | 通过 |
| L4 边界 | `qa/boundary/test_glossary_api_boundary.py` | 5 | 通过 |
| L5 安全 | `qa/security/test_glossary_api_security.py` | 4 | 通过 |
| **合计** | | **29** | **29 通过 / 0 失败** |

行覆盖率（coverage sysmon）：服务层 5 文件合计 **95%**
（security 96% / source_api 95% / source_db 95% / loader 98% / service 93%），满足铁律 ≥95%。

## 关键覆盖点

1. SSRF：回环/链路本地/元数据/未指定地址拒绝，企业内网私有网段放行；创建/更新/测试/同步四入口统一前置校验；
2. 凭据：加密存储、响应掩码（不回显明文/密文）、明文容忍；
3. API 源：GET/POST、headers/params、json_path 提取、非 JSON/4xx/超限/非数组错误路径；
4. DB 源：连接参数校验、表列表、SQL/表模式 LIMIT 追加、连接失败传播；
5. 同步：列映射（column_aliases）、外部词条 pending、幂等 upsert、批内同名去重（修复唯一冲突 bug）、last_synced_at；
6. 定时同步：list_syncable_bases（sync_enabled + active，按创建时间升序）、arq cron 小时可配置、单术语集失败不中断；
7. 权限：viewer 只读、editor 可写、非成员 403、跨 KB 隔离、并发创建同名词条仅一成功（咨询锁）；
8. 边界：重名 409、空名/超长、非法 source_type、导入上限、manual 同步拒绝。

## 测试中发现并修复的缺陷

1. SSRF ValueError 未转业务异常（500）→ 服务/API 统一转 400；
2. 批内同名导入统一 flush 前不可见触发唯一冲突 → 批内聚合去重；
3. list_syncable_bases 无排序导致 limit 截断不稳定 → 按创建时间升序。

## 迁移代码审查（S2）

- 原项目无用能力未迁移（文本标准化/术语合并/旧兼容端点）；
- 无调试残留、未使用 import 已清理（--fix + 人工核对）；
- term_base_loader 接口在方案与 docstring 双重登记（C6），抽取阶段禁止重复建设。

## 结论

S2 通过铁律验收：29/29，服务层覆盖率 95%，安全（SSRF/凭据/权限/并发）与定时同步验证通过。
