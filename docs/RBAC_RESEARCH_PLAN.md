# 用户角色权限管理改造方案（调研 + 设计）

> 本文档基于对市面主流 RAG 产品（Dify / FastGPT / RAGFlow / AnythingLLM /
> MaxKB / Open WebUI）官方文档的调研，结合 HansonDOC RAG 当前代码现状，
> 给出用户角色权限管理的**目标模型与分期改造方案**。
> 现状结论均来自仓库源码；市场结论均附官方来源，未找到的细节明确标注。

## 1. 当前实现盘点（源码事实）

### 1.1 已存在的能力

| 能力 | 实现 | 代码位置 |
|------|------|----------|
| 用户表（启停/超管/软删/失败锁定/最近登录） | `User` ORM | [user.py](/home/grainuser/hansonDoc_RAG/backend/app/models/user.py) |
| 登录/刷新/资料/改密/注册/重置 | `auth` 路由 | [auth.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/auth.py) |
| 超管判定（布尔开关） | `is_superuser` + `require_superuser` | [deps.py](/home/grainuser/hansonDoc_RAG/backend/app/api/deps.py) |
| 用户管理 CRUD（仅超管） | `users` 路由 | [users.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/users.py) |
| 知识库 RBAC 骨架：owner/admin/editor/viewer | 角色常量 + `KbMember` | [knowledge_base.py](/home/grainuser/hansonDoc_RAG/backend/app/models/knowledge_base.py) |
| KB 上下文与 RLS 骨架 | `KBContext` / `activate_rls` / `require_role` | [deps.py](/home/grainuser/hansonDoc_RAG/backend/app/api/deps.py) |
| 敏感操作审计 | `audit_action` 中间件 | [audit_log.py](/home/grainuser/hansonDoc_RAG/backend/app/middleware/audit_log.py) |
| 管理端 IP 白名单 | 见后端配置 | `backend/app/core/config.py` |

### 1.2 明确缺失

- **无系统级角色表**：系统层只有 `is_superuser` 布尔值，没有 admin/member/auditor 等细分角色。
- **无权限矩阵**：没有“权限点 → 角色”的映射表，新增端点只能手写 `require_superuser`。
- **无资源级可见性模型**：KB 骨架已预留 `KbMember`，但缺少成员邀请、审批、到期、移交流程。
- **无工作空间/团队概念**：所有用户平铺在单一系统空间内。
- **无 API Key 管理**：无独立于 JWT 的服务间/API 访问凭证。
- **无自定义角色**：角色集合硬编码为 4 个 KB 角色。

## 2. 市场调研（官方来源）

### 2.1 产品权限模型对比

| 产品 | 角色模型 | 资源级权限 | 邀请/审批 | 其他亮点 |
|------|----------|------------|-----------|----------|
| **Dify** | Owner / Admin / Editor / Normal（企业版可自定义角色模板） | 应用、知识库各自设置“谁可见/可编辑” | 邀请制，72h 过期；所有权转让需验证码 | 每个工作空间仅 1 个 Owner；Admin 管成员与模型供应商 |
| **FastGPT** | 成员 / 部门 / 群组三种维度；资源可授权“可管理/可读/可调用” | 应用、知识库直接按成员授权 | 团队邀请 | 部门与群组权限按“并集”原则生效 |
| **RAGFlow** | 团队 Owner + 成员；商业版扩展两级权限系统 | 数据集权限：仅自己 / 团队；可共享解析与检索 | 团队邀请，接受后可见共享数据集 | 开源版权限较简，商业版补齐 mutation 端点管控 |
| **AnythingLLM** | Admin / Manager / Default（可自定义角色权限） | Workspace 成员显式授权 | 管理员创建用户 | Manager 可看所有工作空间但不能改 LLM/向量库配置 |
| **MaxKB** | 系统管理员 / 工作空间管理员 / 普通用户 | 智能体、知识库、工具、模型逐资源授权（管理/编辑/只读） | 成员+角色批量添加 | 对话用户独立体系；默认权限=角色权限 |
| **Open WebUI** | Admin / User / Pending | Permission 功能开关（删除聊天/联网搜索/API Key 等） | 注册默认 pending，需管理员批准 | 三层：角色（信任基线）+ 权限（功能开关）+ 组（批量授权）；Admin 豁免所有权限 |

### 2.2 调研来源

- Dify：<https://docs.dify.ai/en/cloud/use-dify/workspace/team-members-management>、
  <https://enterprise-docs.dify.ai/en/3.11.x/administer/admin-console-rbac-help>
- FastGPT：<https://doc.fastgpt.io/en/guide/workspace/team/team_roles_permissions>、
  <http://doc.fastgpt.io/zh-CN/docs/introduction/guide/team_permissions/team_roles_permissions>
- RAGFlow：<https://github.com/infiniflow/ragflow/blob/main/docs/guides/team/share_knowledge_bases.md>、
  <https://github.com/infiniflow/ragflow/blob/main/docs/guides/team/join_or_leave_team.md>、
  <https://github.com/infiniflow/ragflow/pull/15164>
- AnythingLLM：<https://docs.anythingllm.com/features/security-and-access>、
  <https://deepwiki.com/Mintplex-Labs/anything-llm/4.2-multi-user-management>
- MaxKB：<https://maxkb.cn/docs/v2/user_manual/X-Pack/authorization_resources/>、
  <https://maxkb.cn/docs/v2/user_manual/X-Pack/workspace/>、
  <https://github.com/1Panel-dev/MaxKB/releases/tag/v2.0.0>
- Open WebUI：<https://docs.openwebui.com/features/authentication-access/rbac/roles/>、
  <https://docs.openwebui.com/features/authentication-access/rbac/permissions/>

## 3. 差距分析（当前 → 目标）

| 维度 | 当前 | 目标 | 参考产品 |
|------|------|------|----------|
| 系统角色 | 布尔超管 | 4 个系统角色（超级管理员/管理员/普通成员/待审批） | Open WebUI、MaxKB |
| 资源权限 | 仅预留 KB 四角色 | 应用/知识库/工具/模型统一 ACL + 默认权限 | FastGPT、MaxKB、Dify |
| 成员加入 | 无邀请 | 邀请链接 + 审批（pending）+ 过期 | Dify、Open WebUI |
| 权限点 | 硬编码 | permission 表 + 角色权限矩阵 + API 校验 | Open WebUI、Dify Enterprise |
| 自定义角色 | 无 | 支持克隆/新建角色并分配权限 | Dify Enterprise、AnythingLLM |
| 所有权 | 不可移交 | 所有权转移（带确认/验证） | Dify |
| 审计 | 已有基础 | 权限变更、授权操作全量审计 | 全行业基线 |
| 部门/群组 | 无 | P2 阶段引入，按并集授权 | FastGPT |

## 4. 目标模型：双层 RBAC + 资源 ACL

```
┌─────────────────────────── 系统层 RBAC ───────────────────────────┐
│ 超级管理员 super_admin    系统全量权限（唯一，不可删除自身）          │
│ 管理员     admin          用户/角色/邀请/系统配置管理                 │
│ 普通成员   member         使用被授权的资源                            │
│ 待审批     pending        可登录但仅可见审批页/个人中心              │
└─────────────────────────── 资源层 ACL ───────────────────────────┐
│ 知识库/应用/工具/模型：owner → admin → editor → viewer（默认继承）  │
│ 成员关系：KbMember(user_id, kb_id, role, status, expires_at)       │
│ 权限语义：可管理（成员/配置）/ 可编辑（内容）/ 可读（检索）/ 无      │
└───────────────────────────────────────────────────────────────────┘
```

### 4.1 系统角色与权限点

建议初始系统角色：

| 角色 | 说明 | 核心权限点 |
|------|------|------------|
| `super_admin` | 系统最高权限，唯一且不可删除 | `system.*`、`user.*`、`role.*`、`audit.*`、`workspace.*` |
| `admin` | 日常运维与成员管理 | `user.manage`、`role.view`、`invite.manage`、`audit.view` |
| `member` | 平台使用者 | `kb.create`、`kb.view`、`kb.edit`（受 ACL 约束） |
| `pending` | 待审批账号 | `profile.self`、`audit.view_own` |

权限点命名建议（新增端点统一挂载）：
`{resource}.{action}`，如 `kb.create` / `kb.delete` / `user.manage` /
`role.manage` / `invite.send` / `apikey.manage` / `audit.export`。

### 4.2 数据模型设计（新增表）

| 表 | 关键字段 | 说明 |
|----|----------|------|
| `roles` | `code`、`name`、`description`、`is_system`、`sort_order` | 系统/自定义角色 |
| `permissions` | `code`、`name`、`resource_type`、`description` | 权限点字典 |
| `role_permissions` | `role_id`、`permission_id` | 角色↔权限多对多 |
| `user_roles` | `user_id`、`role_id`、`scope`（system/workspace）、`workspace_id` | 用户↔角色多对多 |
| `workspaces` | `name`、`owner_id`、`config` | 工作空间（P1） |
| `workspace_members` | `workspace_id`、`user_id`、`role`、`status`、`invited_by`、`expires_at` | 空间成员与邀请状态 |
| `kb_members`（扩展） | 新增 `status`、`invited_by`、`expires_at`、`created_at` | 资源级成员授权 |
| `invitations` | `token`、`target_type`、`target_id`、`role`、`expires_at`、`used_at` | 邀请单 |
| `api_keys` | `user_id`、`name`、`scopes`、`last_used_at`、`revoked_at` | API 凭证 |
| `audit_logs`（扩展） | 复用现有表，补充 `role_before`/`role_after` | 权限变更审计 |

### 4.3 后端改造点（标注文件）

1. **角色与权限核心**
   - 新增 `backend/app/models/rbac.py`：`Role` / `Permission` / `RolePermission` / `UserRole`。
   - 新增 `backend/app/services/rbac_service.py`：初始化系统角色、权限矩阵、角色分配。
   - 新增 `backend/app/api/v1/endpoints/roles.py`：角色 CRUD、权限矩阵维护（super_admin 专属）。
2. **依赖与校验升级**
   - 改造 [deps.py](/home/grainuser/hansonDoc_RAG/backend/app/api/deps.py)：
     `require_superuser` 扩展为 `require_permission("user.manage")`；
     `get_current_active_user` 增加 `pending` 角色拦截（仅允许个人中心与审批页）。
   - 保留并复用现有 `KBContext` / `require_role` / `activate_rls`，将角色来源迁移到 `user_roles`。
3. **用户管理升级**
   - 改造 [users.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/users.py) 与
     [user_service.py](/home/grainuser/hansonDoc_RAG/backend/app/services/user_service.py)：
     创建用户可分配系统角色；支持停用/删除时回收角色；保留超管自保规则。
4. **邀请与审批**
   - 新增 `backend/app/api/v1/endpoints/invitations.py`：发送邀请、撤销、接受、审批。
   - 注册流程改造（[auth.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/auth.py)）：
     新注册默认 `pending`，与 Open WebUI 一致（可用配置关闭审批制）。
5. **资源 ACL 落地**
   - 扩展 [knowledge_base.py](/home/grainuser/hansonDoc_RAG/backend/app/models/knowledge_base.py)：
     `KbMember` 增加邀请字段；`ALL_ROLES` 保留四角色并映射到权限点。
   - 新增通用 `require_resource_permission(resource_type, actions)` 依赖，统一各资源端点。
6. **API Key**
   - 新增 `backend/app/api/v1/endpoints/api_keys.py` 与 `backend/app/models/api_key.py`；
     鉴权链路支持 Bearer API Key（只读/写入按 scopes 校验）。
7. **所有权转移**
   - 新增服务函数：Owner 转移需目标成员确认 + 审计留痕（参考 Dify 验证码机制）。
8. **审计强化**
   - 扩展 [audit_log.py](/home/grainuser/hansonDoc_RAG/backend/app/middleware/audit_log.py)：
     角色分配/回收、邀请发送/审批、API Key 创建/吊销均强制审计。
9. **数据库迁移**
   - 新增 Alembic 迁移脚本（`backend/alembic/versions/`），含角色/权限种子数据。

### 4.4 前端改造点（标注文件）

1. **路由与守卫**
   - 改造 `frontend/src/router.tsx`（若存在）或 `AppShell`：按权限点渲染菜单与路由。
   - 新增 `frontend/src/stores/rbac.ts`：缓存当前用户角色与权限点。
2. **管理页面**
   - 新增 `frontend/src/views/admin/RolesPage.tsx`：角色列表、权限矩阵（勾选式）。
   - 改造 [UsersPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/admin/UsersPage.tsx)：
     用户角色选择、状态徽章（pending/admin/member）、邀请记录。
   - 新增 `frontend/src/views/admin/InvitationsPage.tsx`：邀请发送/撤销/过期。
   - 新增 `frontend/src/views/ProfilePage.tsx` 内“API Key”区块（或独立页面）。
3. **个人中心**
   - 展示系统角色与空间角色徽章、待审批状态；Pending 用户登录后仅见审批提示。
4. **权限矩阵组件**
   - 新增 `frontend/src/components/RolePermissionMatrix.tsx`，表格化权限点勾选。

## 5. 分期落地

### P0（当前阶段之后第一优先级：角色化）

- 建表 + Alembic 迁移 + 系统角色/权限点种子。
- `require_permission` 依赖上线，用户管理端点全部挂权限点。
- 前端 RolesPage + 用户角色分配；前端路由按权限点过滤。

### P1（资源级 ACL 与邀请）

- `KbMember` 扩展（status/expires_at/invited_by）。
- 邀请发送/接受/审批流；注册默认 pending（配置开关）。
- 知识库等资源端点接入通用 ACL；所有权转移。
- 前端邀请管理页 + 资源成员面板。

### P2（工作空间与群组）

- `workspaces` / `workspace_members` 上线，引入空间维度。
- 部门/群组按并集授权（FastGPT 模式）；自定义角色编辑器。
- API Key 管理 + 审计导出。

## 6. 风险与兼容

1. **存量数据**：现有 `is_superuser=true` 用户迁移为 `super_admin` 角色，其余为 `member`；
   迁移脚本必须可回滚。
2. **自保规则**：`super_admin` 至少保留一名；禁止自己删除自己或回收自己角色（沿用
   [user_service.py](/home/grainuser/hansonDoc_RAG/backend/app/services/user_service.py) 现有自保逻辑）。
3. **前端兼容**：路由守卫改造前，菜单按 `user.is_superuser` 与权限点双条件渲染，避免未授权页面闪现。
4. **审计覆盖**：所有角色/权限变更必须有审计，避免权限成为盲区。
5. **性能**：权限点校验在依赖层完成（单次查询角色+权限），避免端点内逐资源重复查询。

## 7. 术语对照（补充条目）

| 术语 | 含义 |
|------|------|
| 系统角色（System Role） | 平台级角色：super_admin / admin / member / pending |
| 空间角色（Workspace Role） | 工作空间内角色：owner / admin / editor / viewer |
| 权限点（Permission Code） | `{resource}.{action}` 形式的细粒度权限标识 |
| ACL | 资源级访问控制：单个资源上“谁、什么角色、什么状态” |
| Pending | 待审批账号状态，仅能访问个人中心与审批页 |
| 邀请单（Invitation） | 带 token、角色、过期时间的加入凭证 |
