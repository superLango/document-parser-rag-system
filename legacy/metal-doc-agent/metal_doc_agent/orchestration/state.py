"""Orchestration state contract (M3.1-02).

The state only holds pointers and summaries: Markdown pages, tables and records
stay in artifacts. Every retry increments a counter, every terminal node writes
a reason, and the whole state is JSON-serialisable for checkpoint/resume.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..contracts import Artifact, Contract


class Budget(Contract):
    max_steps: int = 12
    max_ocr_retries: int = 2
    max_extract_retries: int = 2
    max_reference_docs: int = 8


class RetryCounters(Contract):
    ocr: int = 0
    extract: int = 0


class RouteInfo(Contract):
    queue: Literal["production", "explore", "human"] = "production"
    recipe_id: str | None = None
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class StepError(Contract):
    code: str
    stage: str
    message: str = ""
    retryable: bool = True


class CostUsage(Contract):
    steps: int = 0
    ocr_pages: int = 0
    extract_calls: int = 0
    model_tokens: int = 0
    elapsed_ms: float = 0.0


class StepRecord(Contract):
    node: str
    at: str
    ms: float = 0.0
    status: str = "ok"
    detail: dict[str, Any] = Field(default_factory=dict)


Stage = Literal[
    "plan",
    "extract",
    "ocr_gate",
    "reocr",
    "route",
    "validate",
    "repair",
    "coverage",
    "assemble",
    "publish_gate",
    "publish",
    "human",
    "fail",
]


class OrchestrationState(Artifact):
    job_id: str
    doc_id: str | None = None
    stage: Stage = "plan"
    status: Literal["running", "published", "review", "human", "failed"] = "running"
    attempt: int = 0
    budget: Budget = Field(default_factory=Budget)
    retries: RetryCounters = Field(default_factory=RetryCounters)
    artifacts: dict[str, str] = Field(default_factory=dict)
    errors: list[StepError] = Field(default_factory=list)
    route: RouteInfo = Field(default_factory=RouteInfo)
    cost: CostUsage = Field(default_factory=CostUsage)
    history: list[StepRecord] = Field(default_factory=list)
    terminal_reason: str | None = None
    options: dict[str, str] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

    def save(self, path) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path) -> "OrchestrationState":
        from pathlib import Path

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
