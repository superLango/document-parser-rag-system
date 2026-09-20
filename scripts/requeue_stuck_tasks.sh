#!/usr/bin/env bash
# 卡住任务巡检与重投（outbox 自愈的运维入口）
#
# 背景：outbox 行若在 claim 之后、enqueue 之前中断（worker 重启 / Redis 作业丢失），
# 会永久停在 claimed/enqueued；claim_outbox 只捞 pending → 永不重投，
# 表现为“接口返回已触发，但任务一直不动”。
#
# 用法：
#   ./requeue_stuck_tasks.sh            # 只巡检并打印（默认 dry-run）
#   ./requeue_stuck_tasks.sh --apply    # 执行重投与僵尸任务收尾
#
# 环境变量（默认值适配 docker compose 项目 hansondoc）：
#   PG_CONTAINER=hansondoc-postgres-1  PG_USER=hansondoc  PG_DB=hanson_doc_rag
#   STUCK_SECONDS=300                   # 超过多久未开工视为卡住
set -euo pipefail

PG_CONTAINER="${PG_CONTAINER:-hansondoc-postgres-1}"
PG_USER="${PG_USER:-hansondoc}"
PG_DB="${PG_DB:-hanson_doc_rag}"
STUCK_SECONDS="${STUCK_SECONDS:-300}"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

psql() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -A -F' | ' "$@"; }

echo "=== 1) outbox 状态分布 ==="
psql -c "SELECT status, count(*) AS cnt, min(created_at) AS oldest FROM task_outbox GROUP BY status ORDER BY cnt DESC;"

echo
echo "=== 2) 卡住的 outbox 行（claimed/enqueued 超 ${STUCK_SECONDS}s 且关联任务仍为 queued） ==="
psql -c "
SELECT o.id, o.type, o.status, o.enqueued_at, t.status AS task_status, t.task_id
  FROM task_outbox o
  LEFT JOIN document_tasks t ON t.task_id = o.task_id
 WHERE o.status IN ('claimed','enqueued')
   AND COALESCE(o.enqueued_at, o.created_at) < now() - make_interval(secs => ${STUCK_SECONDS})
   AND t.status = 'queued'
 ORDER BY o.created_at;"

echo
echo "=== 3) 僵尸 DocumentTask（仍 queued 但 outbox 已完成） ==="
psql -c "
SELECT t.task_id, t.type, t.status, t.created_at
  FROM document_tasks t
  JOIN task_outbox o ON o.task_id = t.task_id
 WHERE t.status = 'queued' AND o.status = 'done'
 ORDER BY t.created_at;"

echo
echo "=== 4) 心跳超时的 running 任务（仅报告，历史作业可能仍在跑） ==="
psql -c "
SELECT task_id, type, status, heartbeat_at,
       round(extract(epoch FROM now() - heartbeat_at)) AS idle_seconds
  FROM document_tasks
 WHERE status = 'running' AND (heartbeat_at IS NULL OR heartbeat_at < now() - interval '15 minutes')
 ORDER BY heartbeat_at NULLS FIRST;"

if [[ "$APPLY" != "1" ]]; then
  echo
  echo "（dry-run，未做任何修改；加 --apply 执行修复）"
  exit 0
fi

echo
echo "=== 执行修复 ==="
psql -c "
UPDATE task_outbox o
   SET status = 'pending', enqueued_at = NULL
 WHERE o.status IN ('claimed','enqueued')
   AND COALESCE(o.enqueued_at, o.created_at) < now() - make_interval(secs => ${STUCK_SECONDS})
   AND EXISTS (SELECT 1 FROM document_tasks t WHERE t.task_id = o.task_id AND t.status = 'queued')
RETURNING id, type;"

psql -c "
UPDATE document_tasks t
   SET status = 'completed', updated_at = now(),
       error = '{\"message\":\"僵尸任务收尾：outbox 已完成但任务未回写\"}'::jsonb
 WHERE t.status = 'queued'
   AND EXISTS (SELECT 1 FROM task_outbox o WHERE o.task_id = t.task_id AND o.status = 'done')
RETURNING task_id, type;"

echo "修复完成：派发器（每 TASK_DISPATCH_INTERVAL_SECONDS 秒）会在下一轮自动重投 pending 行。"
