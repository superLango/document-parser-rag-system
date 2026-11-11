"""Self-heal route (isolated from the production extraction route).

Everything in this package is opt-in: importing it never touches production
artifacts, never opens the self-heal database, and never registers routes.
Enable it with ``SELFHEAL_ENABLED=1`` in the standalone ``apps/selfheal``
service only.
"""

from __future__ import annotations

SELFHEAL_VERSION = "0.1.0"

__all__ = ["SELFHEAL_VERSION"]
