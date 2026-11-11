# apps/worker

单任务 worker 入口。

```powershell
# 在仓库根目录运行
python apps/worker/main.py --job-id <job_id>
python apps/worker/main.py --once          # 处理当前队列后退出
python apps/worker/main.py --watch         # 常驻轮询（默认 2 秒）
python apps/worker/main.py --job "..\标准文件\Q-Du 302-2015.md" --out runs\qdu302
```

- 引擎实现：`metal-doc-agent/metal_doc_agent/worker.py`
- 任务状态与 API 共用 `JobStore`（`data/jobs/{job_id}/state.json`）
- 平台侧设置 `HANSON_INLINE_JOBS=0` 后只入队，由 `--watch` 消费

M1.9 后续会替换为 arq/Redis 常驻 worker；job 契约保持不变。
