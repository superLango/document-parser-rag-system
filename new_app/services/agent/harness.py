"""Agent harness: guardrails, tool loop, sessions and checkpoint/resume."""

from __future__ import annotations

import json
import time
from typing import Any

from hanson_contracts import (
    AgentResult,
    AgentResumeRequest,
    AgentSession,
    AgentStep,
    AgentTask,
    ModelMessage,
    ToolCall,
)

from .context import ContextManager, ContextOverflow
from .model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from .prompts import PromptLibrary, PromptRef
from .schema import validate_json_schema
from .session import SessionStore
from .tools import ToolRegistry


class AgentHarness:
    def __init__(
        self,
        gateway: ModelGateway,
        context_manager: ContextManager,
        tools: ToolRegistry,
        sessions: SessionStore,
        prompts: PromptLibrary,
        *,
        clock=time.monotonic,
    ) -> None:
        self.gateway = gateway
        self.context_manager = context_manager
        self.tools = tools
        self.sessions = sessions
        self.prompts = prompts
        self._clock = clock

    async def run(self, task: AgentTask) -> AgentResult:
        prompt = self.prompts.resolve(task.role, task.prompt_id)
        return await self._run(task, prompt)

    async def resume(self, request: AgentResumeRequest) -> AgentResult:
        session = self.sessions.get(request.session_id)
        if session is None:
            raise ValueError(f"session not found: {request.session_id}")
        if session.status in {"completed", "cancelled"}:
            return _result_from_session(session)
        task = request.task or self.sessions.get_task(session.session_id)
        if task is None:
            raise ValueError(f"task not found for session: {request.session_id}")
        session.status = "running"
        session.error_code = None
        session.error_message = ""
        prompt = self.prompts.load(session.prompt_id or "harness.v1")
        if request.additional_input:
            context = dict(session.context)
            history = list(context.get("history") or [])
            history.append(
                ModelMessage(
                    role="user",
                    content="Human input: "
                    + json.dumps(request.additional_input, ensure_ascii=False, sort_keys=True),
                ).model_dump()
            )
            context["history"] = history
            session.context = context
            session.status = "running"
            self.sessions.save(session, task)
        return await self._run(task, prompt, session=session)

    async def _run(
        self,
        task: AgentTask,
        prompt: PromptRef,
        *,
        session: AgentSession | None = None,
    ) -> AgentResult:
        session = session or self.sessions.create(
            task, prompt.prompt_id, prompt.sha256
        )
        context_payload = dict(session.context or {})
        history = [
            ModelMessage.model_validate(item) for item in context_payload.get("history") or []
        ]
        tool_outputs = list(context_payload.get("tool_outputs") or [])
        inputs = dict(task.inputs or {})
        input_facts = list(inputs.get("facts") or [])
        input_decisions = list(inputs.get("decisions") or [])
        evidence_ids = [str(item) for item in inputs.get("evidence_ids") or []]
        header_paths = inputs.get("header_paths") or []
        units = [str(item) for item in inputs.get("units") or []]
        fields = [str(item) for item in inputs.get("fields") or []]
        context_manager = ContextManager(
            self.context_manager.tokenizer,
            max_tokens=min(task.budget.max_tokens, self.context_manager.max_tokens),
            l1_ratio=self.context_manager.l1_ratio,
            l2_ratio=self.context_manager.l2_ratio,
            l3_ratio=self.context_manager.l3_ratio,
        )
        started = self._clock()
        loop_keys: set[str] = set()
        invalid_outputs = 0
        tool_call_count = len(session.tool_calls)
        step_index = len(session.steps)
        protocol = _protocol_prompt(task, self.tools.catalog(task.tools))

        while step_index < task.budget.max_steps:
            if self._clock() - started > task.budget.wall_time_seconds:
                return self._fail(session, task, "AGENT_WALL_TIME", "wall time exceeded")
            try:
                state = await context_manager.assemble(
                    prompt.text + "\n\n" + protocol,
                    task.objective,
                    facts=input_facts,
                    history=history,
                    tool_outputs=tool_outputs,
                    schema=task.output_schema,
                    decisions=input_decisions,
                    evidence_ids=evidence_ids,
                    header_paths=header_paths,
                    units=units,
                    fields=fields,
                )
            except ContextOverflow as exc:
                return self._fail(session, task, "AGENT_CONTEXT_OVERFLOW", str(exc))
            messages = context_manager.render_messages(state)
            response = None
            try:
                value, response = await self.gateway.chat_json(messages)
            except ModelUnavailable as exc:
                return self._fail(session, task, "AGENT_MODEL_UNAVAILABLE", str(exc))
            except ModelOutputInvalid as exc:
                invalid_outputs += 1
                if invalid_outputs >= 2:
                    return self._fail(session, task, "AGENT_OUTPUT_INVALID", str(exc))
                history.append(
                    ModelMessage(
                        role="user",
                        content=(
                            "Your previous response was not valid JSON. "
                            "Return one JSON action only."
                        ),
                    )
                )
                session.usage.model_calls += 1
                if response is not None:
                    session.usage.prompt_tokens += response.prompt_tokens
                self.sessions.save(session, task)
                step_index += 1
                continue
            session.usage.model_calls += 1
            session.usage.prompt_tokens += response.prompt_tokens
            session.usage.completion_tokens += response.completion_tokens
            session.usage.total_tokens += response.total_tokens
            step_index += 1
            session.steps.append(
                AgentStep(
                    index=step_index,
                    kind="model",
                    at=_now(),
                    duration_ms=response.latency_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    detail={"endpoint": response.endpoint},
                )
            )

            action = str(value.get("action") or "") if isinstance(value, dict) else ""
            if action == "human":
                session.status = "waiting_human"
                session.output = {"reason": value.get("reason", "")}
                session.checkpoint = step_index
                self._save_context(session, history, tool_outputs, task)
                self.sessions.save(session, task)
                return _result_from_session(session)

            if action == "tool":
                name = str(value.get("tool") or "")
                arguments = value.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}
                if tool_call_count >= task.budget.max_tool_calls:
                    return self._fail(
                        session, task, "AGENT_BUDGET_EXCEEDED", "max tool calls exceeded"
                    )
                key = name + ":" + json.dumps(arguments, ensure_ascii=False, sort_keys=True)
                if key in loop_keys:
                    return self._fail(
                        session, task, "AGENT_LOOP_DETECTED", f"repeated tool call {name}"
                    )
                loop_keys.add(key)
                tool_call_count += 1
                session.usage.tool_calls += 1
                result = await self.tools.execute(name, arguments, task.tools, inputs)
                call_status = (
                    "succeeded"
                    if result.ok
                    else ("denied" if result.denied else "failed")
                )
                session.tool_calls.append(
                    ToolCall(
                        call_id=f"call-{tool_call_count}",
                        name=name,
                        arguments=arguments,
                        status=call_status,
                        result=result.value,
                        error=result.error,
                        started_at=_now(),
                        finished_at=_now(),
                    )
                )
                session.steps.append(
                    AgentStep(
                        index=step_index,
                        kind="tool",
                        at=_now(),
                        detail={"tool": name, "ok": result.ok},
                    )
                )
                history.append(
                    ModelMessage(role="assistant", content=json.dumps(value, ensure_ascii=False))
                )
                history.append(
                    ModelMessage(
                        role="tool",
                        name=name,
                        content=json.dumps(result.as_dict(), ensure_ascii=False, default=str),
                    )
                )
                tool_outputs.append(
                    {
                        "call_id": f"call-{tool_call_count}",
                        "content": json.dumps(result.as_dict(), ensure_ascii=False, default=str),
                        "summary": result.error or name,
                    }
                )
                session.checkpoint = step_index
                self._save_context(session, history, tool_outputs, task)
                self.sessions.save(session, task)
                continue

            output = value.get("output") if action == "final" else value
            if not isinstance(output, dict):
                return self._fail(session, task, "AGENT_OUTPUT_INVALID", "output must be an object")
            errors = validate_json_schema(output, task.output_schema) if task.output_schema else []
            if errors:
                invalid_outputs += 1
                if invalid_outputs >= 2:
                    return self._fail(
                        session, task, "AGENT_OUTPUT_INVALID", "; ".join(errors)[:1000]
                    )
                history.append(
                    ModelMessage(
                        role="user",
                        content="Your output failed schema validation: "
                        + "; ".join(errors)[:1000]
                        + ". Return the corrected final JSON.",
                    )
                )
                session.checkpoint = step_index
                self._save_context(session, history, tool_outputs, task)
                self.sessions.save(session, task)
                continue
            session.status = "completed"
            session.output = output
            session.checkpoint = step_index
            session.steps.append(
                AgentStep(index=step_index, kind="final", at=_now(), detail={})
            )
            self._save_context(session, history, tool_outputs, task)
            self.sessions.save(session, task)
            return _result_from_session(session)

        return self._fail(session, task, "AGENT_BUDGET_EXCEEDED", "max steps exceeded")

    def _save_context(
        self,
        session: AgentSession,
        history: list[ModelMessage],
        tool_outputs: list[dict[str, Any]],
        task: AgentTask,
    ) -> None:
        session.context = {
            "history": [message.model_dump() for message in history],
            "tool_outputs": tool_outputs,
            "task": task.model_dump(mode="json"),
        }

    def _fail(
        self,
        session: AgentSession,
        task: AgentTask,
        code: str,
        message: str,
    ) -> AgentResult:
        session.status = "failed"
        session.error_code = code
        session.error_message = message[:1000]
        self.sessions.save(session, task)
        return _result_from_session(session)


def _protocol_prompt(task: AgentTask, catalog: list[dict[str, Any]]) -> str:
    return (
        "Task tools (whitelist):\n"
        + json.dumps(catalog, ensure_ascii=False, sort_keys=True)
        + "\nOutput schema:\n"
        + json.dumps(task.output_schema or {}, ensure_ascii=False, sort_keys=True)
        + "\nReturn exactly one JSON action per turn."
    )


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def _result_from_session(session: AgentSession) -> AgentResult:
    status = session.status
    if status not in {"completed", "waiting_human", "failed"}:
        status = "failed"
    return AgentResult(
        task_id=session.task_id,
        session_id=session.session_id,
        status=status,  # type: ignore[arg-type]
        output=session.output or {},
        usage=session.usage,
        steps=len(session.steps),
        error_code=session.error_code,
        error_message=session.error_message,
        prompt_id=session.prompt_id,
        prompt_hash=session.prompt_hash,
    )
