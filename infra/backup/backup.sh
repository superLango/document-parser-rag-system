#!/usr/bin/env bash
# Backup platform Postgres, engine/platform data and object storage (M5.1-05).
# Usage: BACKUP_PASSPHRASE=... BACKUP_DIR=/backups ./backup.sh
#        BACKUP_ENCRYPTION=none ./backup.sh   # only for local/dev drills
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups/$(date -u +%Y%m%dT%H%M%SZ)}
NAMESPACE=${NAMESPACE:-metal-agent}
DATABASE_URL=${DATABASE_URL:-}
MINIO_ALIAS=${MINIO_ALIAS:-hanson}
MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
MINIO_BUCKET=${MINIO_BUCKET:-documents}
ENCRYPTION=${BACKUP_ENCRYPTION:-openssl}
PASSPHRASE=${BACKUP_PASSPHRASE:-}
PASSPHRASE_FILE=${BACKUP_PASSPHRASE_FILE:-}

if [ "$ENCRYPTION" != "none" ]; then
  if [ -z "$PASSPHRASE" ] && [ -n "$PASSPHRASE_FILE" ]; then
    PASSPHRASE=$(cat "$PASSPHRASE_FILE")
  fi
  if [ -z "$PASSPHRASE" ]; then
    echo "BACKUP_PASSPHRASE or BACKUP_PASSPHRASE_FILE is required when encryption is on" >&2
    exit 2
  fi
fi

mkdir -p "$BACKUP_DIR"

echo "[1/5] postgres dump"
if [ -n "$DATABASE_URL" ]; then
  pg_dump --no-owner --format=custom "$DATABASE_URL" > "$BACKUP_DIR/platform.dump"
else
  kubectl -n "$NAMESPACE" exec deploy/platform-api -- \
    sh -c 'pg_dump --no-owner --format=custom "$HANSON_DATABASE_URL"' \
    > "$BACKUP_DIR/platform.dump"
fi

echo "[2/5] engine + platform data"
kubectl -n "$NAMESPACE" exec deploy/engine-api -- tar czf - -C /data engine \
  > "$BACKUP_DIR/engine-data.tgz"
kubectl -n "$NAMESPACE" exec deploy/platform-api -- tar czf - -C /data platform \
  > "$BACKUP_DIR/platform-data.tgz"

echo "[3/5] object storage mirror"
if command -v mc >/dev/null 2>&1; then
  mc mirror --overwrite "$MINIO_ALIAS/$MINIO_BUCKET" "$BACKUP_DIR/objects"
  tar czf "$BACKUP_DIR/objects.tgz" -C "$BACKUP_DIR" objects
  rm -rf "$BACKUP_DIR/objects"
else
  echo "mc not installed; skipping object mirror" >&2
fi

echo "[4/5] encrypt artifacts"
encrypt_artifact() {
  local file=$1
  if [ "$ENCRYPTION" = "none" ]; then
    return 0
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required for backup encryption" >&2
    exit 2
  fi
  openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
    -in "$file" -out "$file.enc" -pass env:BACKUP_PASSPHRASE
  rm -f "$file"
}
export BACKUP_PASSPHRASE="$PASSPHRASE"
for artifact in platform.dump engine-data.tgz platform-data.tgz objects.tgz; do
  if [ -f "$BACKUP_DIR/$artifact" ]; then
    encrypt_artifact "$BACKUP_DIR/$artifact"
  fi
done

echo "[5/5] checksum + manifest"
( cd "$BACKUP_DIR" && sha256sum ./* > SHA256SUMS )
if [ "$ENCRYPTION" != "none" ]; then
  : > "$BACKUP_DIR/HMAC-SHA256SUMS"
  for encrypted in "$BACKUP_DIR"/*.enc; do
    mac=$(openssl dgst -sha256 -hmac "$PASSPHRASE" "$encrypted" | awk '{print $NF}')
    printf '%s  %s\n' "$mac" "$(basename "$encrypted")" >> "$BACKUP_DIR/HMAC-SHA256SUMS"
  done
fi
cat > "$BACKUP_DIR/manifest.json" <<EOF
{"created_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","namespace":"$NAMESPACE","encryption":"$ENCRYPTION","files":$(find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%f\n' | wc -l)}
EOF

if [ -n "${PUSHGATEWAY_URL:-}" ]; then
  printf 'backup_last_success_timestamp_seconds %s\n' "$(date +%s)" \
    | curl -sS --data-binary @- "$PUSHGATEWAY_URL/metrics/job/backup" >/dev/null
fi

echo "backup complete: $BACKUP_DIR"
