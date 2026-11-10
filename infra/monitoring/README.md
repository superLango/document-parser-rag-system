# 监控与告警

- `prometheus-rules.yaml`：SLO 记录规则与告警（API down、积压、失败率、模型端点、备份失败）。
- `grafana-dashboard.json`：任务状态、三队列、复核量、p95 延迟、模型端点。

## 指标来源

| 指标 | 来源 |
|---|---|
| `engine_jobs`、`engine_queue_items`、`engine_feedback_events` | 引擎 `/metrics` |
| `engine_pipeline_seconds_bucket`、`engine_pipeline_seconds_sum` | 引擎 `/metrics`（由每个任务的 `metrics.json` 汇总） |
| `platform_documents`、`platform_field_review_events` | 平台 `/platform/metrics`（同时代理引擎指标） |
| `up{job="model-extract"}`、`up{job="model-sft"}`、`up{job="model-ocr"}` | Prometheus 抓取 1.35 的 vLLM `/metrics` |
| `up{job="model-layout"}` | 版面服务无 `/metrics`，抓取 `:9978/health`（200 即 up） |
| `backup_last_success_timestamp_seconds` | 备份脚本推送（pushgateway/textfile，见 `infra/backup/backup.sh`） |

## 抓取配置（示例）

```yaml
scrape_configs:
  - job_name: engine-api
    metrics_path: /metrics
    static_configs:
      - targets: ["engine-api.metal-agent.svc:8010"]
  - job_name: platform-api
    metrics_path: /platform/metrics
    static_configs:
      - targets: ["platform-api.metal-agent.svc:8000"]
  - job_name: model-extract
    metrics_path: /metrics
    static_configs:
      - targets: ["192.168.188.75:9991"]
  - job_name: model-sft
    metrics_path: /metrics
    static_configs:
      - targets: ["192.168.188.75:9991"]
  - job_name: model-ocr
    metrics_path: /metrics
    static_configs:
      - targets: ["192.168.188.75:9977"]
  - job_name: model-layout
    metrics_path: /health
    static_configs:
      - targets: ["192.168.188.75:9978"]
```

## 校验

```bash
promtool check rules infra/monitoring/prometheus-rules.yaml
python -c "import json; json.load(open('infra/monitoring/grafana-dashboard.json'))"
```

指标实际输出可在平台容器验证：`/platform/metrics` 同时包含 `engine_jobs{status=...}`、`engine_pipeline_seconds_bucket{le=...}`、`platform_documents{status=...}`。
