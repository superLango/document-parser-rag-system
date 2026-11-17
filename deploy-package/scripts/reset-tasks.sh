#!/usr/bin/env bash
# Clear all parse tasks while keeping uploaded documents.
# Removes runs, artifacts metadata, events, feedback, integration tasks and shadow data.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_NAME="${PROJECT_NAME:-hanson}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f docker-compose.yml)

if [[ "${1:-}" != "--yes" ]]; then
  echo "This deletes ALL parse tasks/runs but keeps documents and original PDFs."
  read -r -p "type YES to continue: " answer
  [[ "$answer" == "YES" ]] || { echo "aborted"; exit 1; }
fi

"${COMPOSE[@]}" exec -T postgres psql -U hanson -d hanson -v ON_ERROR_STOP=1 <<'SQL'
\echo '== before =='
SELECT 'documents' AS table_name, count(*) FROM documents
UNION ALL SELECT 'runs', count(*) FROM runs
UNION ALL SELECT 'artifacts', count(*) FROM artifacts
UNION ALL SELECT 'integration_tasks', count(*) FROM integration_tasks;

BEGIN;
DELETE FROM accepted_snapshots;
DELETE FROM promotions;
DELETE FROM feedback;
DELETE FROM integration_tasks;
DELETE FROM shadow_batches;
DELETE FROM shadow_documents;
DELETE FROM runs;
UPDATE documents SET status = 'uploaded';
UPDATE standard_index SET latest_run_id = NULL;
COMMIT;

\echo '== after =='
SELECT 'documents' AS table_name, count(*) FROM documents
UNION ALL SELECT 'runs', count(*) FROM runs
UNION ALL SELECT 'artifacts', count(*) FROM artifacts
UNION ALL SELECT 'integration_tasks', count(*) FROM integration_tasks;
SQL

echo
echo "tasks cleared. Original PDFs remain in object storage; artifacts metadata was removed."
echo "note: artifact objects in MinIO are not deleted by this script."
