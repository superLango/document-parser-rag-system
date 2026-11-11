"""Agent runtime composition and dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from hanson_contracts import AgentResult, AgentResumeRequest, AgentTask

from .agents import ReviewAgent, RouterAgent
from .config import Settings
from .context import ContextManager, build_tokenizer
from .harness import AgentHarness
from .model_gateway import ModelGateway, ModelGatewayConfig
from .prompts import PromptLibrary
from .session import SessionStore
from .tools import build_default_registry

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        endpoints = settings.endpoints()
        self.gateway = ModelGateway(
            ModelGatewayConfig(
                model=settings.model,
                endpoints=endpoints,
                failover_seconds=settings.failover_seconds,
                cooldown_seconds=settings.cooldown_seconds,
                timeout_seconds=settings.timeout_seconds,
                max_tokens=settings.max_output_tokens,
                api_key=settings.api_key,
                max_context_tokens=settings.context_window,
                enable_thinking=settings.enable_thinking,
            )
        )
        self.tokenizer = build_tokenizer(
            settings.tokenizer_mode,
            base_url=endpoints[0].base_url,
            model=settings.model,
        )
        self.context_manager = ContextManager(
            self.tokenizer, max_tokens=settings.context_window
        )
        self.sessions = SessionStore(settings.session_db)
        self.tools = build_default_registry()
        self.prompts = PromptLibrary(settings.prompt_dir)
        self.harness = AgentHarness(
            self.gateway,
            self.context_manager,
            self.tools,
            self.sessions,
            self.prompts,
        )
        self.router = RouterAgent(
            self.gateway, self.context_manager, self.sessions, self.prompts
        )
        self.review = ReviewAgent(
            self.gateway, self.context_manager, self.sessions, self.prompts
        )
        self._probe_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            await self.gateway.probe()
        except Exception:  # noqa: BLE001 - startup must not fail on a dead endpoint
            logger.exception("initial model endpoint probe failed")
        if self._probe_task is None:
            self._probe_task = asyncio.create_task(self.gateway.probe_loop())

    async def close(self) -> None:
        if self._probe_task is not None:
            self._probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._probe_task
            self._probe_task = None
        await self.gateway.close()
        await self.tokenizer.close()
        self.sessions.close()

    async def run(self, task: AgentTask) -> AgentResult:
        task = task.model_copy(deep=True)
        task.budget.max_steps = min(task.budget.max_steps, self.settings.max_steps)
        task.budget.max_tool_calls = min(
            task.budget.max_tool_calls, self.settings.max_tool_calls
        )
        task.budget.wall_time_seconds = min(
            task.budget.wall_time_seconds, self.settings.wall_time_seconds
        )
        if task.role == "router":
            return await self.router.run(task)
        if task.role == "review":
            return await self.review.run(task)
        return await self.harness.run(task)

    async def resume(self, request: AgentResumeRequest) -> AgentResult:
        return await self.harness.resume(request)

    async def health(self) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "tokenizer_mode": self.settings.tokenizer_mode,
            "context_window": self.settings.context_window,
            "watchdog_floor_mb": self.settings.watchdog_floor_mb,
            "sessions_db": str(self.settings.session_db),
            "endpoints": [item.as_dict() for item in self.gateway.status()],
            "models": await self.gateway.health(),
        }
