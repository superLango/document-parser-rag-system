# 外部安全评审包（E3）

> 状态：**待外部评审**。本文件把代码侧证据、攻击面与待确认项整理成可评审材料；评审通过前不得上线。

## 1. 评审范围

| 项 | 内容 |
|---|---|
| 系统 | 标准文档解析平台（web / platform-api / engine / worker / 模型平面） |
| 部署 | 内网 K8s（`metal-agent`），模型平面独立 GPU 主机 `192.168.1.35` |
| 数据 | 标准原文、解析结果、证据、复核事件、反馈集、审计日志 |
| 外部接口 | 无第三方 API；仅内网模型服务（GLM-OCR / Qwen3.5-9B / adapter shim） |
| 代码入口 | `apps/api`、`apps/web`、`metal-doc-agent`、`infra/` |

## 2. 控制清单

| 域 | 控制 | 证据 |
|---|---|---|
| 认证 | Bearer 用户令牌 / API Key（SHA-256 存储、可吊销、带 scope） | `apps/api/hanson_api/auth.py`、平台测试 |
| 授权 | 知识库成员校验 + `documents:write`；复核/确认需用户令牌 | 平台测试、`docs/security.md` §1 |
| 审计 | `audit_logs` + append-only `field_review_events` + `feedback.jsonl` | 迁移 `h4e5f6a7b8c9`、平台测试 |
| 密钥 | K8s Secret / ExternalSecret；仓库扫描 0 findings | `eval/security-scan.json`、`infra/security/check_secrets.py` |
| 网络 | 默认拒绝入站；引擎出站仅模型平面 CIDR + Pod + DNS | `infra/k8s/network-policy.yaml`（`192.168.1.35/32`） |
| 备份 | openssl AES-256-CBC（PBKDF2 100k）+ 校验和 + 篡改检测 | `infra/backup/{backup,restore}.sh`、`eval/backup-drill.md` |
| 容器 | 非 root（uid 1000）、只读挂载按需、资源限制 | `infra/k8s/engine.yaml` |
| 依赖 | 版本固定；建议 CI 接 `pip-audit` / `npm audit` / Trivy | `pyproject.toml`、`package.json` |

## 3. 已知风险（需评审确认接受或整改）

| 风险 | 状态 | 建议 |
|---|---|---|
| 分享链接 HMAC 短期 token | 已实现 | 生产加 IP/UA 绑定 + 速率限制 |
| 无全局限流 | 未实现 | Ingress/应用层限流 |
| 内网明文 HTTP / 未 mTLS | 未实现 | Service Mesh 或 TLS 终止 |
| 备份口令由环境变量注入 | 已实现 | 接 KMS/ExternalSecret，定期轮换 |
| 外部渗透测试 | 未执行 | 上线前完成，高危清零 |

## 4. 证据索引

- 代码侧安全说明：[security.md](security.md)
- 密钥扫描：[eval/security-scan.json](../metal-doc-agent/eval/security-scan.json)
- 备份恢复演练：[eval/backup-drill.md](../metal-doc-agent/eval/backup-drill.md)
- 网络策略：[network-policy.yaml](../infra/k8s/network-policy.yaml)
- SLO/容量：[slo.md](slo.md)
- 试点验收：[pilot-acceptance.md](pilot-acceptance.md)

## 5. 评审方检查清单

- [ ] 认证/授权边界（越权、IDOR、令牌生命周期）
- [ ] 文件上传与解析沙箱（路径穿越、压缩炸弹、PDF 解析）
- [ ] 模型端点内网隔离与出站白名单
- [ ] 备份加密与密钥管理（KMS、轮换、恢复权限）
- [ ] 审计日志完整性与保留周期
- [ ] 依赖 CVE 与镜像扫描
- [ ] 限流、TLS/mTLS、分享链接防滥用

## 6. 排期与签字

| 项 | 值 |
|---|---|
| 评审方 | 待定 |
| 计划日期 | 待定 |
| 高危结论 | 待评审 |
| 整改截止 | 待评审 |

| 角色 | 姓名 | 日期 | 结论 |
|---|---|---|---|
| 安全负责人 |  |  | 待签 |
| 技术负责人 |  |  | 待签 |

> 未完成外部评审与高危清零前，E3 仍为 G5 阻塞项。
