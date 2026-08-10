# 系统重构路线图

## 1. 背景

旧版（`document-parser-rag-system/`）核心能力完整，但存在以下结构问题
（详见根目录调研结论）：

- `backend/app/models/` 整包缺失，系统当前无法启动/迁移；
- 多次重构残留大量死代码、占位实现与断链端点；
- 全局 API 与 KB API 双套并存；
- 前端（Vue 3）与后端耦合的调优注释/硬编码过多。

因此进行系统性重构：**前端换 React，后端保留 Python 但重建工程结构**。

## 2. 重构原则

1. **规范先行**：本仓库 `docs/` 为唯一权威规范，代码向规范对齐。
2. **增量迁移**：按阶段推进，每阶段结束系统可运行、可验证。
3. **冻结基线**：旧代码只读，作为行为参照与迁移素材，不原地大改。
4. **先数据后界面**：先保证后端可用与数据完整，再迁移界面。
5. **无静默回退**：沿用旧系统“配置缺失即报错、全量校验”的原则。

## 3. 阶段路线图

| 阶段 | 目标 | 主要交付物 | 涉及路径（目标仓库） |
|------|------|-----------|---------------------|
| P0 | 仓库与规范就绪 | 本仓库规范文件、Git 初始化、基线归档 | `/`、`docs/` |
| P1 | 后端重建 | `backend/` 骨架、ORM models 补齐、迁移可执行、启动通过 | `backend/app/`、`backend/alembic/` |
| P2 | 后端收敛 | 删除死代码/双套 API、配置收口、CI 与测试恢复 | `backend/app/api/`、`backend/app/core/`、`.github/` |
| P3 | 前端骨架 | React 脚手架、主题落地、通用组件、路由与鉴权 | `frontend/` |
| P4 | 前端页面迁移 | 登录/KB/文档/抽取/术语/图谱/问答/管理/嵌入预览 | `frontend/src/features/` |
| P5 | 联调与下线 | 新旧并行验证 → 旧 Vue 前端下线、文档更新 | `document-parser-rag-system/frontend/` |

## 4. 旧 → 新迁移矩阵（初始版，随重构细化）

### 4.1 前端页面

| 旧（Vue） | 新（React） |
|-----------|-------------|
| `src/views/Login.vue` | `frontend/src/features/auth/` |
| `src/views/Kb/*`（List/Create/Overview/Documents/Extraction/ExtractionConfig/QA/Graph/Terms/Tasks/Search/Members/PromptEditor/ScriptManager/TestPanel 等） | `frontend/src/features/kb/` 按域拆分 |
| `src/views/admin/*` | `frontend/src/features/admin/` |
| `src/views/embed/ExtractionPreview.vue` | `frontend/src/features/embed/` |
| `src/views/Dashboard.vue` 等 | `frontend/src/features/dashboard/` |

### 4.2 后端模块

| 旧模块 | 迁移策略 |
|--------|---------|
| `app/models/*`（缺失） | P1 重建，ORM 与 Alembic 001 对齐 |
| `app/api/v1/endpoints/*`（23 个） | 收敛为 KB 化 API 为主，删除全局旧端点 |
| `app/services/*`（8 大域） | 保留职责划分，重写工程结构、去除延迟导入 |
| `app/tasks/*` | 保留 arq 体系，删除注释残留，修复 Redis 配置 |
| `app/domain_templates/*`、`app/kb_hooks/*` | 原样迁移，纳入配置中心 |
| `frontend/`（Vue） | P5 下线，React 全面替代 |

## 5. 风险与回滚

- **models 缺失**：P1 必须优先解决，否则后端不可运行；
  反推生成需与现网库/迁移脚本核对。
- **API 兼容**：公开一体化接口与统一响应体保持契约不变
  （见 `docs/API_CONTRACT.md`），外部系统不受影响。
- **数据安全**：数据库迁移前备份；KB 物理资源销毁逻辑只在删除 KB 时触发。
- **回滚策略**：每阶段提交独立可回滚；基线目录不改动，随时可对照。
