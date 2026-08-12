# 术语集外部源连接 500 修复报告（S8 缺陷修复）

- 日期：2026-08-12
- 现象：新建术语集选择“接口拉取/数据库”源，点击“测试连接”返回 500（服务器内部错误）。

## 根因

1. **端点异常捕获不全**：`test-api` / `test-db` / `db-tables` / `preview-sql`
   四个端点只捕获 `ValueError`（SSRF/参数校验），而外部连接真实失败时抛出的是
   `httpx.HTTPError`（超时/拒绝连接）与 `aiomysql` 异常，未捕获 → 全局 500。
2. **隐藏缺陷（连带发现）**：`source_db._conn_kwargs` 传入了
   `read_timeout` 参数，但 `aiomysql.connect`（0.3.2）不支持该参数，
   导致数据库源连接**任何时候都会失败**；此前被 500 掩盖，修复后暴露出
   “数据库连接失败：connect() got an unexpected keyword argument 'read_timeout'”。

## 修复内容

| 文件 | 修改 |
|------|------|
| `backend/app/services/glossary/source_api.py` | `_run` 捕获 `httpx.TimeoutException`→`API 连接超时（Ns）`、`httpx.HTTPError`→`API 请求失败（类型）：详情`，统一转 `RuntimeError` |
| `backend/app/services/glossary/source_db.py` | `_connect` 捕获连接异常→`数据库连接失败：详情`；查询路径统一转 `RuntimeError`；移除不支持的 `read_timeout` 参数 |
| `backend/app/api/v1/endpoints/kb_glossary.py` | 四个外部源端点补捕 `(ValueError, RuntimeError, TypeError)` → 业务 400 |

同步路径 `sync_term_base` 已捕获 `(ValueError, RuntimeError)`，客户端包装后同样受益，不再 500。

## 验证

| 项目 | 结果 |
|------|------|
| 真实复现：API 不可达（超时） | ✅ 400 `API 连接超时（10s）` |
| 真实复现：DB 不可达 | ✅ 400 `数据库连接失败：...` |
| 空 SQL 预览 | ✅ 400 `SQL 不能为空` |
| SSRF 拒绝 | ✅ 400（原有路径不变） |
| 新增单测：httpx 连接/超时包装 | ✅ 通过 |
| 新增边界：API/DB 连接异常转 400、空 SQL 400 | ✅ 通过 |
| 术语模块五层全量回归 | ✅ 66/66 |
| S4 主页 E2E（含 API 失败提示） | ✅ 10/10 |
| ruff | ✅ 通过 |

测试文件：
- `qa/unit/test_glossary_s2_coverage.py`（新增连接/超时包装用例）
- `qa/boundary/test_glossary_api_boundary.py`（新增 S2-06/07/08）

## 影响面

- 前端无需改动：失败信息由后端 400 message 提供，toast 展示“API 连接失败/数据库连接失败 + 具体原因”。
- 手动同步与 arq 定时同步的外部源错误现在也会得到友好错误，不再冒 500。
