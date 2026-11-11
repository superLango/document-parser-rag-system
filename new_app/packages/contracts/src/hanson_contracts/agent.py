"""Agent runtime contracts shared by agent, review and orchestration services."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentRole = Literal["router", "review", "repair", "triage"]
AgentStatus = Literal["running", "completed", "waiting_human", "failed", "cancelled"]


class AgentBudget(BaseModel):
    max_steps: int = Field(default=24, ge=1, le=200)
    max_tool_calls: int = Field(default=32, ge=0, le=500)
    max_tokens: int = Field(default=64000, ge=1024, le=262144)
    wall_time_seconds: float = Field(default=300.0, gt=0, le=3600)


class AgentTask(BaseModel):
    task_id: str
    trace_id: str
    role: AgentRole
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    budget: AgentBudget = Field(default_factory=AgentBudget)
    prompt_id: str = ""
    checkpoint_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "succeeded", "failed", "denied"] = "pending"
    result: Any = None
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""


class AgentStep(BaseModel):
    index: int
    kind: Literal["model", "tool", "final", "error", "compaction", "segment"]
    at: str
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0


class AgentSession(BaseModel):
    session_id: str
    task_id: str
    trace_id: str
    role: AgentRole
    status: AgentStatus = "running"
    objective: str = ""
    prompt_id: str = ""
    prompt_hash: str = ""
    steps: list[AgentStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: AgentUsage = Field(default_factory=AgentUsage)
    context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str = ""
    checkpoint: int = 0
    created_at: str = ""
    updated_at: str = ""


class AgentResult(BaseModel):
    task_id: str
    session_id: str
    status: Literal["completed", "waiting_human", "failed"] = "completed"
    output: dict[str, Any] = Field(default_factory=dict)
    usage: AgentUsage = Field(default_factory=AgentUsage)
    steps: int = 0
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str = ""
    prompt_id: str = ""
    prompt_hash: str = ""
    degraded: bool = False


class AgentResumeRequest(BaseModel):
    session_id: str
    task: AgentTask | None = None
    additional_input: dict[str, Any] = Field(default_factory=dict)


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str = ""


class ModelResponse(BaseModel):
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    endpoint: str = ""
    model: str = ""
    latency_ms: int = 0


class RouteAssignment(BaseModel):
    table_id: str
    recipe_id: str
    version: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    assignments: list[RouteAssignment] = Field(default_factory=list)
    fallback: Literal["human", "generic", "fail"] = "fail"
    confidence: float = Field(default=0.0, ge=0, le=1)


class ReviewFinding(BaseModel):
    category: str
    severity: Literal["info", "warning", "error"] = "warning"
    target: dict[str, Any] = Field(default_factory=dict)
    observed: str | None = None
    expected: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: Literal["deterministic", "model"] = "deterministic"
    rule_id: str = ""


class ReviewReport(BaseModel):
    status: Literal["pass", "warn", "fail"] = "pass"
    findings: list[ReviewFinding] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    ruleset_version: str = "m5"
    degraded: bool = False
    prompt_id: str = ""
    prompt_hash: str = ""


class ReviewRequest(BaseModel):
    run_id: str = ""
    trace_id: str = ""
    records: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    template: dict[str, Any] = Field(default_factory=dict)
    deterministic_findings: list[ReviewFinding] = Field(default_factory=list)
