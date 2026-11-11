#!/usr/bin/env bash
# GLM-OCR 联调冒烟：验证模型服务、容器连通性，并用 OCR 适配器跑一次真实识别。
set -euo pipefail

GLM_URL="${GLM_URL:-http://192.168.1.35:9977/v1}"
GLM_MODEL="${GLM_MODEL:-GLM-OCR}"
OCR_CONTAINER="${OCR_CONTAINER:-hanson-new-app-ocr-1}"

echo "[1/3] 宿主机访问 GLM"
curl -fsS -m 8 "$GLM_URL/models" | head -c 120
echo

echo "[2/3] OCR 容器访问 GLM"
docker exec "$OCR_CONTAINER" python -c \
  "import urllib.request; print('  status', urllib.request.urlopen('$GLM_URL/models', timeout=8).status)"

echo "[3/3] GLM + 表格算法完整链路"
docker exec -i \
  -e GLM_OCR_BASE_URL="$GLM_URL" \
  -e GLM_OCR_MODEL="$GLM_MODEL" \
  "$OCR_CONTAINER" python - <<'PY'
import asyncio

import pymupdf

from services.ocr.config import settings
from services.ocr.contracts import OcrRequest
from services.ocr.service import parse_document
from services.shared.storage import build_store

doc = pymupdf.open()
page = doc.new_page()
for y in (72, 100, 128, 156):
    page.draw_line((72, y), (400, y))
for x in (72, 180, 290, 400):
    page.draw_line((x, 72), (x, 156))
for x, y, text in (
    (80, 92, "Grade"),
    (190, 92, "Rm MPa"),
    (300, 92, "A %"),
    (80, 120, "Q355B"),
    (190, 120, "470"),
    (300, 120, "22"),
    (80, 148, "Q235B"),
    (190, 148, "400"),
    (300, 148, "26"),
):
    page.insert_text((x, y), text, fontsize=10)
data = doc.tobytes()

request = OcrRequest(document_id="glmcheck", storage_key="", filename="t.pdf")
store = build_store(settings.storage_config())


async def run():
    await store.ensure_ready()
    return await parse_document(data, request, store)


result = asyncio.run(run())
print("  backend =", result.backend)
print("  pages =", len(result.pages))
print("  quality =", result.quality, "warnings =", result.warnings)
print("  artifacts =", len(result.artifacts))
for table in result.tables:
    print(
        "  table", table.table_id,
        "profile =", table.profile,
        "rows =", table.n_rows,
        "cols =", table.n_cols,
        "header_paths =", table.header_paths,
    )
PY

echo "[glm] SMOKE DONE"
