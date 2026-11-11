"""FastAPI entry point.

Install optional dependencies first:
    pip install -e ".[api]"
Run:
    uvicorn apps.api.main:app --reload
"""

from __future__ import annotations

from metal_doc_agent.api import create_app

app = create_app()
