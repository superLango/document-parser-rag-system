#!/usr/bin/env bash
# 验证 OCR 服务：Markdown/HTML 表格、PDF 渲染与编排端到端产物。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-hanson}"
NAMESPACE="${NAMESPACE:-hanson-standard}"
export PATH="$PATH:$HOME/.local/bin"

NODE_IP="$(docker inspect "${CLUSTER_NAME}-control-plane" \
  --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')"
GATEWAY="http://$NODE_IP:30080"
FIXTURE="$NEW_APP_DIR/tests/fixtures/ocr/mechanical.md"

kubectl -n "$NAMESPACE" port-forward svc/ocr 18012:8002 >/tmp/ocr-port-forward.log 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  if curl -fsS http://localhost:18012/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "[1/3] Markdown + HTML 表格"
result="$(curl -fsS -X POST "http://localhost:18012/internal/ocr/parse-file" \
  -F "file=@${FIXTURE};type=text/markdown")"
printf '%s' "$result" | python3 -c '
import json, sys
data = json.load(sys.stdin)
print("  backend =", data["backend"])
print("  pages =", len(data["pages"]))
print("  quality =", data["quality"], "warnings =", data["warnings"])
print("  artifacts =", len(data["artifacts"]))
for table in data["tables"]:
    print(
        "  table", table["table_id"],
        "profile =", table["profile"],
        "rows =", table["n_rows"],
        "cols =", table["n_cols"],
        "header_rows =", table["header_rows"],
        "header_paths =", table["header_paths"],
    )
'

echo "[2/3] PDF 原生渲染"
kubectl -n "$NAMESPACE" exec -i deploy/ocr -- python - <<'PY'
import asyncio

import pymupdf

from services.ocr.adapters.pdf import PdfOcrAdapter
from services.ocr.contracts import OcrRequest

document = pymupdf.open()
page = document.new_page()
page.insert_text((72, 72), "Table 1 Mechanical properties")
page.insert_text((72, 100), "Q355B 470 MPa")
data = document.tobytes()

request = OcrRequest(document_id="pdfcheck", storage_key="", filename="t.pdf")
output = asyncio.run(PdfOcrAdapter().parse(data, request))
result = output.result
print("  backend =", result.backend)
print("  pages =", len(result.pages))
print("  image_keys =", [page.image_key for page in result.pages])
print("  markdown_len =", len(result.markdown))
print("  assets =", sorted(output.assets))
PY

echo "[3/3] 编排端到端"
doc_json="$(curl -fsS -X POST "$GATEWAY/v1/documents" \
  -F "file=@${FIXTURE};type=text/markdown")"
doc_id="$(printf '%s' "$doc_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
run_json="$(curl -fsS -X POST "$GATEWAY/v1/documents/$doc_id/runs" \
  -H 'Content-Type: application/json' -d '{}')"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
status=""
for _ in $(seq 1 60); do
  status="$(curl -fsS "$GATEWAY/v1/runs/$run_id" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  case "$status" in
    STRUCTURED_READY | FAILED | CANCELLED) break ;;
  esac
  sleep 1
done
echo "  run_id=$run_id status=$status"
curl -fsS "$GATEWAY/v1/runs/$run_id/artifacts" | python3 -c '
import json, sys
for item in json.load(sys.stdin):
    print("  artifact", item["role"], item["storage_key"], item["sha256"][:12])
'

if [ "$status" != "STRUCTURED_READY" ]; then
  echo "[k8s] OCR CHECK FAILED"
  exit 1
fi
echo "[k8s] OCR CHECK DONE"
