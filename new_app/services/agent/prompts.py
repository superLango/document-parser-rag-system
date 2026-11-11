"""Versioned prompt loading and hashing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
DEFAULT_PROMPTS = {
    "router": "router.v1",
    "review": "review.v1",
    "triage": "triage.v1",
    "repair": "repair.v1",
    "generic": "harness.v1",
}


@dataclass(frozen=True)
class PromptRef:
    prompt_id: str
    text: str
    sha256: str


class PromptLibrary:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parent / "prompts"

    def resolve(self, role: str, prompt_id: str = "") -> PromptRef:
        chosen = prompt_id or DEFAULT_PROMPTS.get(role, "harness.v1")
        return self.load(chosen)

    def load(self, prompt_id: str) -> PromptRef:
        if not PROMPT_ID_RE.match(prompt_id) or "/" in prompt_id or ".." in prompt_id:
            raise ValueError(f"invalid prompt id: {prompt_id}")
        path = self.root / f"{prompt_id}.txt"
        if not path.exists():
            raise FileNotFoundError(f"prompt not found: {prompt_id}")
        text = path.read_text(encoding="utf-8").strip()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return PromptRef(prompt_id=prompt_id, text=text, sha256=digest)
