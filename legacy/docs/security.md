# 安全与合规（M5.2-03）

> 状态：代码侧检查完成；外部安全评审与渗透测试**未排期**，不能作为上线批准。

## 1. 认证与授权

- 平台：Bearer 用户令牌或 `X-API-Key`；API Key 仅存 SHA-256，可吊销、带 scope；
- 多租户双层角色：工作空间 `owner/admin/member`，知识库 `owner/editor/viewer`；平台 admin 只管理用户与全局审计，不自动获得业务数据权限；
- 邀请：token 仅存 SHA-256，一次性、可撤销，默认 7 天过期（`HANSON_INVITATION_MINUTES`）；
- API Key：绑定工作空间，可限定 `kb_ids` 白名单；有效角色为创建者角色与 scope 上限（`viewer`/`editor`）取低，创建者停用即失效；
- 知识库成员校验在每个文档/任务接口执行，无超级用户绕过；
- 引擎 API：数据端点默认**不从平台端口暴露**（`/v1/jobs*`、`/v1/recipes`、`/v1/batches` 已移除）；确需暴露时强制 `X-Engine-Token`；引擎独立服务仅内网；
- 业务词典：平台提供鉴权 GET（`/v1/business-dictionary`），引擎原路由不挂平台端口；同步/别名/pending 仅平台 admin；
- 复核/确认/字段事件要求用户令牌 + `documents:write`；确认后文档锁定，重新拆分生成新版本；
- 登录：按“用户名 + 客户端 IP”失败计数，超过阈值返回 429 + `Retry-After`；
- 错误响应统一 `application/problem+json`（`type/title/status/detail/instance`），保留 `detail` 兼容旧客户端；认证头与限流头不丢失。

## 2. 密钥

- `HANSON_SECRET_KEY` 来自 K8s Secret（示例文件仅占位），生产接 ExternalSecret/SealedSecret；
- 数据库口令、MinIO 口令同样只经 Secret 注入；
- 引擎 `.env` 不入库；模型端点无 API key（内网）；
- 仓库内 `infra/security/check_secrets.py` 做基础密钥扫描，CI 应阻断。

## 3. 数据分级与存储

| 级别 | 数据 | 存储 | 访问 |
|---|---|---|---|
| 内部 | 标准原文、解析产物、证据 | 引擎数据卷/对象存储 | 平台成员 |
| 敏感 | 复核事件、反馈集、审计日志 | Postgres | 平台成员 + 审计 |
| 机密 | 密钥、口令 | Secret 管理 | 运维 |

- 本地化部署，不外发模型请求（模型平面内网）；
- 备份使用 openssl AES-256-CBC（PBKDF2 100000 迭代），口令经 `BACKUP_PASSPHRASE`/文件注入；生产仍需接 KMS 并限制读权限。

## 4. 审计

- `audit_logs` 记录登录、上传、解析、复核、字段事件、词典变更，并带 `workspace_id`；
- 审计查询：平台 admin 可全局筛选 `workspace_id/action`；工作空间 owner/admin 仅限本空间（其他成员 403）；
- 字段事件 append-only（`field_review_events`），反馈集 `data/feedback/feedback.jsonl` 只追加；
- 建议开启 Postgres WAL 归档与对象存储版本化，防篡改。

## 5. 供应链

- Python/Node 依赖在 `pyproject.toml`、`package.json` 中固定版本；
- 镜像基础层固定 tag（python:3.11-slim、node:22-alpine、nginx:1.27-alpine、postgres:16-alpine）；
- 未使用未审计的第三方运行时（LangGraph 未引入）；
- 建议 CI：`pip-audit`、`npm audit --omit=dev`、镜像 Trivy 扫描。

## 6. 网络与浏览器安全

- NetworkPolicy 默认拒绝入站；web←ingress，platform←web/ingress，engine←platform；
- 引擎出站仅模型平面 `192.168.1.35/32` + 集群内 Pod + DNS；
- 外部接口白名单：无第三方 API 调用（词典/模型均内网）；
- API 响应统一安全头：`X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy`、`Permissions-Policy`、API 侧 CSP；
- Web（nginx）设置 CSP：`default-src 'self'`、`img-src 'self' data: blob:`、`frame-ancestors 'none'`，并移除 `/engine/` 反代。

## 7. 已知风险与待办

| 风险 | 状态 | 建议 |
|---|---|---|
| 分享链接为 HMAC 短期 token | 已实现 | 生产加 IP/UA 绑定与速率限制 |
| 登录暴力尝试 | 已实现应用层限流 | 多副本需网关/Redis 全局限流 |
| 其余接口无限流 | 未实现 | Ingress/应用层限流 |
| 内部明文 HTTP | 未实现 mTLS | Service Mesh 或 TLS 终止 |
| 备份加密 | 已实现（openssl + 口令注入） | 接 KMS/ExternalSecret 并轮换 |
| 外部渗透测试 | 未执行 | 上线前完成，高危清零 |

## 8. 上线闸门

- [x] 最小权限 RBAC/scope；
- [x] 密钥不落代码（示例占位 + 扫描脚本）；
- [x] 审计日志覆盖关键动作；
- [x] 备份加密与篡改检测（本地演练 PASS）；
- [ ] 外部安全评审无高危（未排期，材料见 [security-review-package.md](security-review-package.md)）。

## 9. 最近一次自动检查（2026-10-29）

- `python infra/security/check_secrets.py --out metal-doc-agent/eval/security-scan.json`
- 结果：`passed=true`，0 findings；
- 覆盖：`.env`/`secret.key` 文件、私钥块、AWS/GitHub/OpenAI/Slack token；
- 未覆盖：依赖 CVE（建议 CI 接 `pip-audit`、`npm audit`、Trivy）、运行期配置漂移。
