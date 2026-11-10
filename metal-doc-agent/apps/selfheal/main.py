"""Standalone self-heal API entry point (default off).

Run from ``metal-doc-agent/``:

    SELFHEAL_ENABLED=1 uvicorn apps.selfheal.main:app --port 8100

The existing platform API (``apps/api``) is not touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.selfheal.api import create_selfheal_app  # noqa: E402

app = create_selfheal_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
