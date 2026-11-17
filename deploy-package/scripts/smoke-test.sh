#!/usr/bin/env bash
# End-to-end smoke test: upload -> poll -> result (optional cleanup).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-.env}"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

GATEWAY_PORT="${GATEWAY_PORT:-18000}"
API="${API_BASE:-http://127.0.0.1:${GATEWAY_PORT}}"
FILE="${SMOKE_FILE:-samples/smoke.pdf}"
CLEANUP=0
[[ "${1:-}" == "--cleanup" ]] && CLEANUP=1

command -v python3 >/dev/null || { echo "python3 is required for JSON parsing" >&2; exit 1; }
[[ -f "$FILE" ]] || { echo "smoke file not found: $FILE" >&2; exit 1; }

json_get() {
  python3 -c '
import json, sys
path = sys.argv[1].split(".")
value = json.load(sys.stdin)
for key in path:
    if isinstance(value, list):
        value = value[int(key)]
    else:
        value = value.get(key)
    if value is None:
        print("")
        raise SystemExit(0)
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
else:
    print(value)
' "$1"
}

KB_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
PROMPT_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"

echo "== health =="
curl -fsS --max-time 5 "${API}/healthz" >/dev/null || { echo "gateway unhealthy" >&2; exit 1; }
echo "gateway ok: ${API}"

echo "== upload =="
UPLOAD="$(curl -sS --max-time 120 -X POST \
  "${API}/api/v1/integration/upload?kb_id=${KB_ID}&prompt_id=${PROMPT_ID}" \
  -F "file=@${FILE};type=application/pdf")"
CODE="$(printf '%s' "$UPLOAD" | json_get code)"
if [[ "$CODE" != "0" ]]; then
  echo "upload failed: $UPLOAD" >&2
  exit 1
fi
TASK_ID="$(printf '%s' "$UPLOAD" | json_get data.task_id)"
DOCUMENT_ID="$(printf '%s' "$UPLOAD" | json_get data.document_id)"
echo "task_id=$TASK_ID document_id=$DOCUMENT_ID"

echo "== poll =="
STATUS=""
for i in $(seq 1 180); do
  STATUS="$(curl -sS --max-time 10 "${API}/api/v1/integration/tasks/${TASK_ID}/status")"
  CODE="$(printf '%s' "$STATUS" | json_get code)"
  OCR="$(printf '%s' "$STATUS" | json_get data.ocr_status)"
  EXT="$(printf '%s' "$STATUS" | json_get data.extract_status)"
  echo "[$i] ocr=${OCR} extract=${EXT}"
  if [[ "$CODE" != "0" ]]; then
    echo "status failed: $STATUS" >&2
    exit 1
  fi
  if [[ "$EXT" == "completed" || "$EXT" == "failed" ]]; then
    break
  fi
  sleep 5
done

if [[ "$EXT" != "completed" ]]; then
  echo "parse did not complete: $(printf '%s' "$STATUS" | json_get data.error)" >&2
  exit 1
fi

echo "== result =="
RESULT="$(curl -sS --max-time 60 "${API}/api/v1/integration/tasks/${TASK_ID}/result")"
CODE="$(printf '%s' "$RESULT" | json_get code)"
TOTAL="$(printf '%s' "$RESULT" | json_get data.summary.total_records)"
CATEGORIES="$(printf '%s' "$RESULT" | json_get data.categories)"
if [[ "$CODE" != "0" || "${TOTAL:-0}" -lt 1 ]]; then
  echo "result invalid: $RESULT" >&2
  exit 1
fi
echo "records=$TOTAL"
printf '%s\n' "$CATEGORIES" | python3 -c '
import json, sys
items = json.load(sys.stdin)
for item in items:
    print("  ", item.get("feature"), ":", item.get("hit_count"))
'

if [[ "$CLEANUP" == "1" ]]; then
  echo "== cleanup =="
  curl -sS -o /dev/null -w "delete document: %{http_code}\n" \
    -X DELETE "${API}/v1/documents/${DOCUMENT_ID}" || true
fi

echo "SMOKE TEST PASSED"
