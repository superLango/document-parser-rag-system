# 回滚手册（新系统 → 旧系统）

> 目标：切换后发生阻断问题时，5 分钟内把统一入口切回旧系统。
> 前置：旧系统保持运行且未修改；入口 upstream 可编辑。
> 关联：[切换方案](../migration/cutover.md)、[演练报告](../reports/M8-cutover-drill.json)

## 1. 触发条件（满足任一即回滚）

- 5 分钟内 5xx > 5%；
- p95 超过基线 2 倍；
- 数据不一致/丢失；
- 无法上传、解析或查看结果；
- 反馈闭环阻断且无法在 15 分钟内恢复。

## 2. 5 分钟回滚步骤

### 第 1 分钟：确认与通报

1. 确认问题范围（入口、API、解析、沙箱、Agent）。
2. 在值班/项目群通报：“开始回滚，预计 5 分钟内完成”。
3. 记录开始时间与现象。

### 第 2 分钟：切回旧系统

本地演练入口（Nginx，18088）：

```bash
# 旧系统 upstream 配置
cat > /tmp/old.conf <<'EOF'
server {
  listen 18088;
  location = /health { proxy_pass http://127.0.0.1:8000/health; }
  location / { proxy_pass http://127.0.0.1:8080/; }
}
EOF

docker cp /tmp/old.conf hanson-cutover-drill:/etc/nginx/conf.d/default.conf
docker exec hanson-cutover-drill nginx -s reload
```

生产 Ingress：把后端 Service 改回旧系统（`kubectl -n <ns> patch ingress ...` 或控制台修改 upstream）。

### 第 3 分钟：验证旧系统

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://<entry>/           # 期望 200
curl -s http://<entry>/health                                      # 期望 {"status":"ok",...}
```

- 用浏览器打开首页，确认可登录/上传/查看旧数据。
- 抽查一条旧文档解析结果。

### 第 4 分钟：隔离新系统

- 停止新系统入口流量（不删除数据）。
- 保留新系统容器/数据库/对象存储，供问题定位。
- 不执行任何旧数据写入或迁移。

### 第 5 分钟：确认与记录

- 通报“回滚完成”，记录结束时间。
- 记录：触发指标、回滚耗时、影响范围、待排查项。
- 新建问题单，附 trace_id/run_id 与日志片段。

## 3. 回滚后处理

| 项 | 动作 |
|---|---|
| 新系统数据 | 保留，不删除 |
| 旧系统数据 | 只读访问，不导入 |
| 词典 | 新系统已导入的词典保留；旧系统词典不受影响 |
| 配置 | 入口保持旧 upstream，直到修复验证 |
| 复测 | 修复后用试点文档复测，重新走灰度 |

## 4. 演练记录

- 日期：2026-11-12
- 入口：`http://localhost:18088`
- 切到旧系统：455 ms；旧 Web 200
- 回切新系统：475 ms
- 结论：满足 ≤5 分钟回滚门槛。

## 5. 注意事项

- 不要删除旧系统容器/数据卷。
- 不要在回滚过程中执行数据库迁移或数据修复。
- 回滚只改入口，不改旧系统代码与数据。
- 若入口本身不可用，直接使用旧系统地址（8080/8000）作为兜底。
