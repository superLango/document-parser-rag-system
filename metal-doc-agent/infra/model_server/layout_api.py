"""PP-DocLayoutV3 HTTP service for metal-doc-agent.

This is a thin wrapper around hansonDoc_RAG's existing layout engine. It is
deployed on the model host (1.35) because the local laptop has no GPU/torch.

Run:
    LAYOUT_MODEL_DIR=/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3 \
    /home/grainuser/hansonDoc_RAG/backend/.venv/bin/python layout_api.py
"""

from __future__ import annotations

import base64
import io
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BACKEND_ROOT = Path("/home/grainuser/hansonDoc_RAG/backend")
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from PIL import Image  # noqa: E402
from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine  # noqa: E402
from app.services.parsekit.types import RenderPage  # noqa: E402

MODEL_DIR = os.environ.get(
    "LAYOUT_MODEL_DIR", "/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3"
)
DEVICE = os.environ.get("LAYOUT_DEVICE") or None
CONF_THRESHOLD = float(os.environ.get("LAYOUT_CONF_THRESHOLD", "0.4"))

_engine: PPDocLayoutEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> PPDocLayoutEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PPDocLayoutEngine(
                    MODEL_DIR,
                    device=DEVICE,
                    conf_threshold=CONF_THRESHOLD,
                )
    return _engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine = get_engine()
    engine._load_model()
    yield


app = FastAPI(title="Metal Doc Layout Service", version="0.1.0", lifespan=lifespan)


class LayoutRequest(BaseModel):
    page_index: int = 1
    width: float | None = None
    height: float | None = None
    dpi: int = 200
    image_base64: str = Field(..., description="PNG base64 or data URL")


class LayoutBlockOut(BaseModel):
    type: str
    bbox: list[float]
    order: int
    confidence: float
    structural: dict = Field(default_factory=dict)


class LayoutResponse(BaseModel):
    schema_version: str = "1.0"
    model: str = "ppdoclayoutv3"
    page_index: int
    width: float
    height: float
    blocks: list[LayoutBlockOut]
    page_failures: list[dict] = Field(default_factory=list)


@app.get("/health")
def health() -> dict:
    engine = get_engine()
    return {
        "status": "ok" if engine._model is not None else "loading",
        "model_loaded": engine._model is not None,
        "model_dir": str(MODEL_DIR),
        "device": engine.device,
        "conf_threshold": CONF_THRESHOLD,
        "failures": len(engine.failures),
    }


def _decode_image(raw: str) -> bytes:
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid image_base64: {exc}") from exc


@app.post("/v1/layout", response_model=LayoutResponse)
def layout(req: LayoutRequest) -> LayoutResponse:
    image_bytes = _decode_image(req.image_base64)
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid image: {exc}") from exc

    width = float(req.width or image.width)
    height = float(req.height or image.height)
    page = RenderPage(
        page_index=req.page_index,
        width=width,
        height=height,
        image_bytes=image_bytes,
    )
    engine = get_engine()
    blocks = engine.analyze([page])[0]
    out = [
        LayoutBlockOut(
            type=block.type,
            bbox=[round(value, 6) for value in block.bbox.as_list()],
            order=index,
            confidence=round(float(block.confidence), 4),
            structural=block.structural or {},
        )
        for index, block in enumerate(blocks, start=1)
    ]
    return LayoutResponse(
        page_index=req.page_index,
        width=width,
        height=height,
        blocks=out,
        page_failures=engine.failures or [],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("LAYOUT_HOST", "0.0.0.0"),
        port=int(os.environ.get("LAYOUT_PORT", "9978")),
        log_level=os.environ.get("LAYOUT_LOG_LEVEL", "info"),
    )
