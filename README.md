# HansonDOC RAG（重构版）

> 系统性重构中的垂直领域文档智能解析与 RAG 问答系统。
> 前端：React；后端：Python；UI 主风格：浅绿色 + 白色。

## 当前状态

- 2026-08-10：**阶段 0 已完成**——项目框架搭建、登录与权限体系改造、工作台上线。
- 旧版完整源码保留在 [`document-parser-rag-system/`](document-parser-rag-system/)，
  作为**冻结基线**与功能参考，重构期间不直接修改。
- 新代码已按 `docs/` 下的规范建设：`backend/`（FastAPI）+ `frontend/`（React）。

## 当前可用功能

- 用户登录（JWT 双令牌、失败锁定、限流）与注册（可配置关闭）
- 个人中心（资料更新、密码修改、密码强度/历史校验、角色徽章展示）
- 角色管理（系统角色/自定义角色、权限矩阵、用户角色分配、菜单/路由按权限点过滤）
- 超级管理员用户管理（CRUD/启停/超管切换/重置密码/软删除）
- 审计日志（敏感操作留痕、脱敏、筛选、统计、详情）
- 工作台（项目信息、用户统计、登录趋势、最近活动）
- 权限基础设施：RBAC 角色、KB 上下文/RLS 骨架、管理端 IP 白名单
- 主数据库：PostgreSQL，库名 `hanson_doc_rag`

> 默认初始管理员：`admin / admin123`（首次登录后请立即修改；
> 可通过 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量覆盖，或关闭 `AUTO_CREATE_ADMIN`）。

## 运行测试

```bash
# 1. 迁移验证（重建测试库 hanson_doc_rag_test，不影响开发库）
bash qa/migration/verify_migration.sh

# 2. 后端五层测试（单测/集成/边界/安全）
cd backend && .venv/bin/python -m pytest -q

# 3. 前端功能场景 E2E（需前后端已启动）
node qa/functional/e2e_p0.mjs
```

测试铁律、模块清单与覆盖率门槛见 [qa/TESTING_PROCESS.md](qa/TESTING_PROCESS.md)。

## 快速启动

```bash
# 1. 创建数据库
createdb hanson_doc_rag

# 2. 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 修改数据库密码 / SECRET_KEY
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. 前端
cd ../frontend
pnpm install
pnpm dev               # http://localhost:5174
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) | 系统迁移计划（阶段 0-8，按域推进） |
| [docs/REFACTORING_PLAN.md](docs/REFACTORING_PLAN.md) | 重构路线图与旧→新迁移矩阵 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 目标系统架构 |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | 技术栈选型与版本策略 |
| [docs/DIRECTORY_STRUCTURE.md](docs/DIRECTORY_STRUCTURE.md) | 目标目录结构 |
| [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | 编码规范（Python / React） |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | API 契约（前后端对齐基线） |
| [docs/UI_THEME.md](docs/UI_THEME.md) | 浅绿+白 UI 主题规范 |
| [docs/UI_INTERACTION.md](docs/UI_INTERACTION.md) | 前端交互与动效规范 |
| [docs/RBAC_RESEARCH_PLAN.md](docs/RBAC_RESEARCH_PLAN.md) | 用户角色权限改造方案（市场调研 + 设计） |
| [qa/TESTING_PROCESS.md](qa/TESTING_PROCESS.md) | 测试实施铁律（五层测试 + 覆盖率门槛） |
| [qa/TEST_CASES.md](qa/TEST_CASES.md) | P0 全部用例（六要素格式） |
| [qa/results/TEST_COVERAGE.md](qa/results/TEST_COVERAGE.md) | P0 覆盖率统计表 |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | 业务常量与自定义术语对照表 |

## 目录概览

```
hansonDoc_RAG/
├── README.md            # 本文件
├── AGENTS.md            # AI 协作与工程规范入口
├── .gitignore
├── docs/                # 全部规范文档
├── qa/                  # 全部测试/迁移测试脚本（统一目录，便于清理）
├── frontend/            # React 前端（登录/工作台/个人中心/用户/角色/审计）
├── backend/             # Python 后端（FastAPI + PostgreSQL hanson_doc_rag）
├── deploy/              # （规划中）部署配置
├── scripts/             # （规划中）工具脚本
└── document-parser-rag-system/   # 旧版冻结基线（只读参考）
```

## 快速约定

- 所有新增功能/改造必须先在 `docs/` 中找到对应规范；无规范先补规范再写代码。
- 引用代码一律标注绝对路径；未在源码中找到的内容明确说明“未找到”，不编造。
- 旧目录 `document-parser-rag-system/` 为冻结基线，除非重构任务明确涉及，不修改。
