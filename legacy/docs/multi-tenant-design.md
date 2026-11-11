# 多租户与权限设计（R3.0）

> 日期：2026-10-31
> 适用范围：`apps/api` 平台面；引擎与 worker 仍以“任务数据 + 工作空间”作为隔离边界。

## 1. 数据模型

```text
User
Workspace ── WorkspaceMember(role: owner|admin|member)
   │
   └── KnowledgeBase(workspace_id) ── KnowledgeBaseMember(role: owner|editor|viewer)
          ├── Document(created_by)
          ├── DocumentTask
          └── AuditLog(workspace_id)

Invitation(workspace_id, role, token_hash, expires_at, accepted_at)
ApiKey(workspace_id, kb_ids, scopes, created_by)
```

- 知识库必须归属一个工作空间；删除工作空间为软删除，知识库随之不可见。
- 文档/任务/结果/复核/分享全部通过知识库归属推导工作空间。
- API Key 绑定一个工作空间，可选知识库白名单；不能跨工作空间。
- 审计事件带 `workspace_id`，旧数据允许为空。

## 2. 角色能力矩阵

| 能力 | WS owner | WS admin | WS member | KB owner | KB editor | KB viewer | 平台 admin |
|---|---|---|---|---|---|---|---|
| 工作空间改名/删除 | ✓ | 改名 | — | — | — | — | — |
| 工作空间成员管理 | ✓ | ✓（不可动 owner） | — | — | — | — | — |
| 创建工作空间 | ✓ | ✓ | ✓ | — | — | — | ✓ |
| 创建知识库 | ✓ | ✓ | ✓ | — | — | — | — |
| 查看工作空间全部 KB | ✓ | ✓ | — | — | — | — | — |
| 知识库成员管理/删除 | ✓ | ✓ | — | ✓ | — | — | — |
| 上传/解析/重试 | ✓ | ✓ | 需 KB editor+ | ✓ | ✓ | — | — |
| 结果/证据/预览读取 | ✓ | ✓ | 需 KB viewer+ | ✓ | ✓ | ✓ | — |
| 新词/字段复核/提交确认 | ✓ | ✓ | 需 KB editor+ | ✓ | ✓ | — | — |
| 分享/导出 | ✓ | ✓ | 需 KB editor+ | ✓ | ✓ | — | — |
| 用户管理/全局审计 | — | — | — | — | — | — | ✓ |

说明：
- 平台 admin 不自动获得任何知识库数据访问权，只做用户管理与全局审计。
- 工作空间 owner/admin 对其下所有知识库拥有 KB owner 等价权限。
- 工作空间 member 只有被加入知识库后才能访问；可创建知识库并成为该 KB owner。
- API Key：读取 scope → 最高 viewer；写 scope → 最高 editor；永远不能管理成员/删除。

## 3. 判定顺序

```text
认证（JWT / API Key）
  → 工作空间成员（不存在 → 403/404）
  → 知识库角色（WS owner/admin → owner；否则 KB member role）
  → scope / 动作最小角色（viewer < editor < owner）
  → 锁定状态 / 文档 review_status 等业务约束
```

- 工作空间不存在或非成员统一返回 404（避免枚举）；存在但角色不足返回 403。
- 知识库非成员统一 403；文档不属于当前 KB 404。
- API Key 还需满足：key.workspace_id == KB.workspace_id；`kb_ids` 非空时 KB 必须在白名单。

## 4. 邀请

- 仅 WS owner/admin 可创建；角色只能是 `admin` 或 `member`。
- 令牌 32 字节随机，数据库只存 SHA-256；明文仅在创建响应出现一次。
- 默认 7 天过期；可撤销；接受时要求登录用户，已成员返回 409；一次性。
- 接受后写入 `workspace_members`，审计 `workspace.invitation.accept`。

## 5. 迁移与回填

1. 新建 `workspaces`、`workspace_members`、`invitations`；
2. `knowledge_bases`、`api_keys`、`audit_logs` 增加 `workspace_id`；
3. 每个既有知识库 owner 建一个“默认工作空间”，owner 写 workspace owner；
4. 既有知识库成员补 workspace member（不覆盖 owner）；
5. 既有 API Key 归入创建者的默认工作空间；
6. 回填后 `knowledge_bases.workspace_id`、`api_keys.workspace_id` 置为非空；
7. 所有步骤可 downgrade。

## 6. 兼容策略

- 旧前端创建知识库不传 `workspace_id`：自动使用用户的第一个 owner/admin 工作空间；没有则创建“个人工作空间”。
- 旧 API Key 创建不传 `workspace_id`：同样落到默认工作空间。
- 旧 `/v1/knowledge-bases` 列表不带 `workspace_id`：返回当前用户所有可访问 KB，并附 `workspace_id`/`role`。
- 引擎任务与产物路径不变，仍按 job 存储；隔离由平台 API 入口保证。

## 7. 已知限制

- 登录限流仍为进程内；多副本需网关/Redis。
- 业务词典为全局配置，暂不按工作空间隔离；同步/别名仅平台 admin。
- 邀请通过链接分发，不内置邮件服务。
