"""Worker entry point for the platform workspace.

Run from the repository root:

    python apps/worker/main.py --job-id <job_id>

The engine package is loaded from ``metal-doc-agent/`` until it moves to
``packages/engine``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "metal-doc-agent"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from metal_doc_agent.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
