#!/usr/bin/env bash
# Restore from a backup produced by backup.sh. Requires explicit CONFIRM=yes.
# Encrypted backups need BACKUP_PASSPHRASE or BACKUP_PASSPHRASE_FILE.
set -euo pipefail

BACKUP_DIR=${1:-}
if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "usage: CONFIRM=yes ./restore.sh <backup-dir>" >&2
  exit 2
fi
if [ "${CONFIRM:-}" != "yes" ]; then
  echo "refusing to restore without CONFIRM=yes" >&2
  exit 3
fi

NAMESPACE=${NAMESPACE:-metal-agent}
DATABASE_URL=${DATABASE_URL:-}
MINIO_ALIAS=${MINIO_ALIAS:-hanson}
MINIO_BUCKET=${MINIO_BUCKET:-documents}
PASSPHRASE=${BACKUP_PASSPHRASE:-}
PASSPHRASE_FILE=${BACKUP_PASSPHRASE_FILE:-}
if [ -z "$PASSPHRASE" ] && [ -n "$PASSPHRASE_FILE" ]; then
  PASSPHRASE=$(cat "$PASSPHRASE_FILE")
fi
export BACKUP_PASSPHRASE="$PASSPHRASE"

TMP_DIR=$(mktemp -d "$(dirname "$BACKUP_DIR")/restore.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[0/5] verify checksums"
( cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS )
if [ -f "$BACKUP_DIR/HMAC-SHA256SUMS" ]; then
  if [ -z "$PASSPHRASE" ]; then
    echo "backup is authenticated; set BACKUP_PASSPHRASE" >&2
    exit 2
  fi
  while read -r mac name; do
    if [ -z "${name:-}" ]; then continue; fi
    actual=$(openssl dgst -sha256 -hmac "$PASSPHRASE" "$BACKUP_DIR/$name" | awk '{print $NF}')
    if [ "$actual" != "$mac" ]; then
      echo "HMAC mismatch for $name (backup tampered or wrong passphrase)" >&2
      exit 1
    fi
  done < "$BACKUP_DIR/HMAC-SHA256SUMS"
  echo "HMAC ok"
fi

echo "[1/5] decrypt artifacts"
decrypt_artifact() {
  local name=$1
  if [ -f "$BACKUP_DIR/$name.enc" ]; then
    if [ -z "$PASSPHRASE" ]; then
      echo "backup is encrypted; set BACKUP_PASSPHRASE" >&2
      exit 2
    fi
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -salt \
      -in "$BACKUP_DIR/$name.enc" -out "$TMP_DIR/$name" -pass env:BACKUP_PASSPHRASE
  elif [ -f "$BACKUP_DIR/$name" ]; then
    cp "$BACKUP_DIR/$name" "$TMP_DIR/$name"
  fi
}
for name in platform.dump engine-data.tgz platform-data.tgz objects.tgz; do
  decrypt_artifact "$name"
done

echo "[2/5] stop writers (scale workers to zero)"
kubectl -n "$NAMESPACE" scale deploy/worker-prod deploy/worker-explore deploy/worker-human --replicas=0

echo "[3/5] restore postgres"
if [ -n "$DATABASE_URL" ]; then
  pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" "$TMP_DIR/platform.dump"
else
  kubectl -n "$NAMESPACE" exec -i deploy/platform-api -- \
    sh -c 'pg_restore --clean --if-exists --no-owner -d "$HANSON_DATABASE_URL"' \
    < "$TMP_DIR/platform.dump"
fi

echo "[4/5] restore data volumes + objects"
kubectl -n "$NAMESPACE" exec -i deploy/engine-api -- tar xzf - -C /data < "$TMP_DIR/engine-data.tgz"
kubectl -n "$NAMESPACE" exec -i deploy/platform-api -- tar xzf - -C /data < "$TMP_DIR/platform-data.tgz"
if [ -f "$TMP_DIR/objects.tgz" ]; then
  tar xzf "$TMP_DIR/objects.tgz" -C "$TMP_DIR"
  if command -v mc >/dev/null 2>&1; then
    mc mirror --overwrite "$TMP_DIR/objects" "$MINIO_ALIAS/$MINIO_BUCKET"
  else
    echo "mc not installed; objects must be restored manually from $TMP_DIR/objects" >&2
  fi
elif [ -d "$BACKUP_DIR/objects" ] && command -v mc >/dev/null 2>&1; then
  mc mirror --overwrite "$BACKUP_DIR/objects" "$MINIO_ALIAS/$MINIO_BUCKET"
fi

echo "[5/5] restart services"
kubectl -n "$NAMESPACE" rollout restart deploy/platform-api deploy/engine-api
kubectl -n "$NAMESPACE" scale deploy/worker-prod --replicas=2
kubectl -n "$NAMESPACE" scale deploy/worker-explore deploy/worker-human --replicas=1
echo "restore complete"
