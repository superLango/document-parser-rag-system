"""Self-heal worker entry point (default off).

Run from ``metal-doc-agent/``:

    SELFHEAL_ENABLED=1 python apps/selfheal/worker.py --once
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metal_doc_agent.selfheal.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
