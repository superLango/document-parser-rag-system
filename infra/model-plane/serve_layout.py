"""PP-DocLayoutV3 HTTP shim for the engine LayoutClient.

Contract (metal-doc-agent/metal_doc_agent/clients/layout.py):

* ``GET /health`` -> ``{"status": "ok", ...}``
* ``POST /v1/layout`` with ``image_base64`` / ``page_index`` / ``dpi`` /
  ``width`` / ``height`` -> ``{"blocks": [{type, bbox, order, confidence,
  structural}]}`` where ``bbox`` is normalized ``[x0, y0, x1, y1]`` in ``[0, 1]``.

The shim reuses hansonDoc_RAG's parsekit PP-DocLayoutV3 engine (the same model
used by its PDF pipeline). It is intentionally model-only: OCR stays on GLM-OCR
``:9977`` and the engine crops blocks from the page image before calling it.
"""

from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(
    os.environ.get("HANSONDOC_BACKEND", "/home/grainuser/hansonDoc_RAG/backend")
).expanduser()
MODEL_DIR = Path(
    os.environ.get(
        "LAYOUT_MODEL_DIR", "/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3"
    )
).expanduser()
DEVICE = os.environ.get("LAYOUT_DEVICE") or None
CONF_THRESHOLD = float(os.environ.get("LAYOUT_CONF_THRESHOLD", "0.4"))
SERVICE_TOKEN = os.environ.get("LAYOUT_SERVICE_TOKEN") or None

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

logger = logging.getLogger("layout-service")

_engine: Any | None = None
_engine_lock = threading.Lock()
_load_error: str | None = None


class LayoutRequest(BaseModel):
    image_base64: str
    page_index: int = 1
    dpi: int = 200
    width: float | None = None
    height: float | None = None


def _load_engine() -> Any:
    global _engine, _load_error
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine

            _engine = PPDocLayoutEngine(
                MODEL_DIR, device=DEVICE, conf_threshold=CONF_THRESHOLD
            )
            _load_error = None
            logger.info(
                "layout model loaded dir=%s device=%s", MODEL_DIR, _engine.device
            )
        except Exception as exc:  # noqa: BLE001 - surface as 503
            _load_error = f"{type(exc).__name__}: {exc}"
            logger.exception("layout model load failed")
            raise
    return _engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        _load_engine()
    except Exception:  # noqa: BLE001 - health reports the failure
        pass
    yield


app = FastAPI(title="PP-DocLayoutV3 Layout Service", version="0.1.0", lifespan=lifespan)


def _check_token(token: str | None) -> None:
    if SERVICE_TOKEN and token != SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid layout token")


@app.get("/health")
def health() -> dict[str, Any]:
    loaded = _engine is not None
    payload: dict[str, Any] = {
        "status": "ok" if loaded else "degraded",
        "service": "layout",
        "model": "PP-DocLayoutV3",
        "model_dir": str(MODEL_DIR),
        "model_dir_exists": MODEL_DIR.exists(),
        "loaded": loaded,
        "device": getattr(_engine, "device", None) if loaded else DEVICE,
    }
    if _load_error:
        payload["error"] = _load_error
    return payload


@app.post("/v1/layout")
def analyze_layout(
    payload: LayoutRequest,
    token: str | None = Header(default=None, alias="X-Layout-Token"),
) -> dict[str, Any]:
    _check_token(token)
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="invalid image_base64") from exc

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        image = image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - invalid image is a 422
        raise HTTPException(status_code=422, detail=f"invalid image: {exc}") from exc

    try:
        engine = _load_engine()
    except Exception as exc:  # noqa: BLE001 - model unavailable is a 503
        raise HTTPException(
            status_code=503, detail=f"layout model unavailable: {exc}"
        ) from exc

    with _engine_lock:
        blocks = engine._infer_page(  # noqa: SLF001 - parsekit's public-ish single-page entry
            image_bytes, float(image.width), float(image.height)
        )

    rows: list[dict[str, Any]] = []
    for order, block in enumerate(blocks):
        rows.append(
            {
                "type": block.type,
                "bbox": [round(float(value), 6) for value in block.bbox.as_list()],
                "order": order,
                "confidence": round(float(block.confidence), 6),
                "structural": block.structural or {},
            }
        )
    return {
        "page_index": payload.page_index,
        "width": image.width,
        "height": image.height,
        "blocks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PP-DocLayoutV3 HTTP service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9978)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
