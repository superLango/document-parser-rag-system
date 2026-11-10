#!/usr/bin/env bash
# Postgres restore drill (C9/E2). Requires pg_dump/pg_restore/psql and a
# scratch database that can be dropped/recreated by the operator.
#
# Usage:
#   DATABASE_URL=postgres://... DRILL_DATABASE_URL=postgres://... \
#     ./postgres_drill.sh
#
# Exits 0 when row counts match for the critical tables.
set -euo pipefail

DATABASE_URL=${DATABASE_URL:?DATABASE_URL is required}
DRILL_DATABASE_URL=${DRILL_DATABASE_URL:?DRILL_DATABASE_URL is required}
OUT=${OUT:-/tmp/postgres-drill.json}
TMP_DIR=$(mktemp -d "/tmp/pgdrill.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[1/4] dump production"
pg_dump --no-owner --format=custom "$DATABASE_URL" > "$TMP_DIR/platform.dump"

echo "[2/4] restore into scratch database"
pg_restore --clean --if-exists --no-owner -d "$DRILL_DATABASE_URL" "$TMP_DIR/platform.dump"

echo "[3/4] compare row counts"
count() {
  local url=$1
  local table=$2
  psql "$url" -Atc "SELECT COUNT(*) FROM $table" 2>/dev/null || echo 0
}
TABLES=${DRILL_TABLES:-documents field_review_events audit_logs}
ok=true
declare -A rows
for table in $TABLES; do
  prod_count=$(count "$DATABASE_URL" "$table")
  drill_count=$(count "$DRILL_DATABASE_URL" "$table")
  rows["$table"]="$prod_count/$drill_count"
  if [ "$prod_count" != "$drill_count" ]; then
    ok=false
  fi
done

echo "[4/4] report"
{
  printf '{"generated_at":"%s","tables":{' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  first=true
  for table in $TABLES; do
    if [ "$first" = true ]; then first=false; else printf ','; fi
    printf '"%s":"%s"' "$table" "${rows[$table]}"
  done
  printf '},"passed":%s}\n' "$ok"
} > "$OUT"
cat "$OUT"
[ "$ok" = true ]
