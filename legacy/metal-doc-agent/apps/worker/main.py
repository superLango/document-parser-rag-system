"""Single-job worker (engine entry point).

Run from ``metal-doc-agent/``:

    python apps/worker/main.py --job-id <job_id>

The implementation lives in :mod:`metal_doc_agent.worker` so the platform
workspace can reuse it without duplicating code.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
