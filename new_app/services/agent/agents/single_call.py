"""Single-call JSON agent used for optional model passes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import AgentResult, AgentStep, AgentTask

from ..context import ContextManager
from ..model_gateway import ModelGateway, ModelOutputInvalid, ModelUnavailable
from ..prompts import PromptLibrary
from ..session import SessionStore

Parser = Callable[[Any, dict[str, Any]], dict[str, Any]]


class SingleCallAgent:
    """One prompt, one JSON answer; parse failures degrade to a fallback dict."""

    def __init__(
        self,
        gateway: ModelGateway,
        context_manager: ContextManager,
        sessions: SessionStore,
        prompts: PromptLibrary,
        *,
        role: str,
        schema: dict[str, Any],
        parse: Parser,
    ) -> None:
        self.gateway = gateway
        self.context_manager = context_manager
        self.sessions = sessions
        self.prompts = prompts
        self.role = role
        self.schema = schema
        self.parse = parse

    async def run(self, task: AgentTask) -> AgentResult:
        prompt = self.prompts.resolve(self.role, task.prompt_id)
        session = self.sessions.create(task, prompt.prompt_id, prompt.sha256)
        degraded = False
        response = None
        try:
            state = await self.context_manager.assemble(
                prompt.text,
                task.objective,
                facts=[
                    {
                        "content": json.dumps(
                            task.inputs, ensure_ascii=False, sort_keys=True
                        ),
                        "immutable": True,
                    }
                ],
                schema=self.schema,
            )
            messages = self.context_manager.render_messages(
                state, instruction="Return only the JSON object."
            )
            value, response = await self.gateway.chat_json(messages)
            output = self.parse(value, task.inputs)
        except (ModelUnavailable, ModelOutputInvalid):
            degraded = True
            output = self.parse(None, task.inputs)
        session.status = "completed"
        session.output = output
        session.steps.append(
            AgentStep(
                index=1,
                kind="final",
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                detail={"degraded": degraded, "model_used": bool(output.get("model_used"))},
            )
        )
        if response is not None:
            session.usage.model_calls += 1
            session.usage.prompt_tokens += response.prompt_tokens
            session.usage.completion_tokens += response.completion_tokens
            session.usage.total_tokens += response.total_tokens
        self.sessions.save(session, task)
        return AgentResult(
            task_id=task.task_id,
            session_id=session.session_id,
            status="completed",
            output=session.output or {},
            usage=session.usage,
            steps=1,
            prompt_id=prompt.prompt_id,
            prompt_hash=prompt.sha256,
            degraded=degraded,
        )
