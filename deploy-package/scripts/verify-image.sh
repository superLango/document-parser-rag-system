set -u
echo "== image import check =="
docker run --rm --platform linux/arm64 --entrypoint python hanson-new-app:local -c "
import fastapi, sqlalchemy, pymupdf
from services.ocr.adapters import glm
from services.ocr.config import settings
print('imports_ok', hasattr(glm, '_request_limit'), settings.glm_ocr_max_concurrency)
"
echo "== tests =="
docker run --rm --platform linux/arm64 --entrypoint python hanson-new-app:local \
  -m pytest tests -k "ocr" -q 2>&1 | tail -8
