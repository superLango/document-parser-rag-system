# 备份恢复演练（M5.1-05 / C9）

## 目标

| 数据 | 方式 | RPO | RTO |
|---|---|---|---|
| Postgres（文档/复核/事件） | `pg_dump` 每日 + WAL 归档（生产） | 24h（WAL 可到 15min） | 2h |
| 引擎/平台数据卷 | 每日 tar | 24h | 2h |
| 对象存储 | `mc mirror` → `objects.tgz` 每日 | 24h | 2h |
| 配方/模型 | Git + 制品仓库版本 | 0（版本固定） | 30min |
| 审计日志 | DB 表只追加 + 归档 | 24h | 2h |

## 加密

- 备份产物（`.dump`/`.tgz`）使用 `openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt` 加密为 `*.enc`；
- 口令来源：`BACKUP_PASSPHRASE` 或 `BACKUP_PASSPHRASE_FILE`（生产接 KMS/ExternalSecret）；
- `SHA256SUMS` 对密文校验；本地演练额外验证 Fernet 认证标签的篡改检测；
- 本地/开发演练可显式 `BACKUP_ENCRYPTION=none`，生产禁止。

## 演练步骤（每季度）

1. 在隔离命名空间 `metal-agent-drill` 恢复最新备份副本；
2. 执行 `BACKUP_PASSPHRASE=... CONFIRM=yes infra/backup/restore.sh <backup-dir>`；
3. Postgres 单独演练：`DATABASE_URL=... DRILL_DATABASE_URL=... infra/backup/postgres_drill.sh`（对比 `documents`/`field_review_events`/`audit_logs` 行数）；
4. 验证：
   - `GET /ready` 返回 ok；
   - 文档数与备份清单一致；
   - 抽查 3 份文档的 `result.json` 与 `field-diff` 可读；
   - 复核事件数与审计日志条数一致；
4. 记录耗时与问题，更新本文件。

## 单组件故障

- **Postgres 故障**：切只读模式，平台 API 返回 503；恢复后重放 WAL。
- **引擎数据卷故障**：从对象存储/备份恢复 `data/engine`，job 状态以 `state.json` 为准。
- **模型端点故障**：引擎降级为 `mock` 或排队，不丢任务（队列保留）。
- **配方/模型回滚**：`configs/recipes/registry.json` 回滚 + 镜像 tag 回退。

## 当前状态（2026-10-29）

- 本地演练：**PASS**（SQLite + 数据卷 + Fernet 加密/解密 + 校验和 + 篡改检测），见 `eval/backup-drill.md`；
- Postgres/K8s 整环境演练：**未执行**（本机无 `pg_dump`/`kubectl`/Docker，需运维在试点环境执行 `postgres_drill.sh` 与 `restore.sh`）；
- 生产密钥管理：待接 KMS/ExternalSecret 并完成轮换演练。
