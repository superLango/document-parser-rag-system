"""v3 抽取 LLM 客户端（AsyncOpenAI 封装，直连 vLLM OpenAI 兼容端点）。

专门为 v3 抽取流程设计，与 ``services/llm/llm_service.py`` 独立：
- 使用 AsyncOpenAI 异步客户端，天然支持高并发（配合 asyncio.Semaphore）
- 针对 vLLM 优化：enable_thinking=False、top_k、chat_template_kwargs
- JSON 解析三级容错（直接 parse → 代码块提取 → 修复）
- 支持长文本截断保护

两条线路共用此客户端：
- glmocr 线路：``chat_json`` 方法，temperature=0.0，直接 prompt
- LangExtract 线路：内部自行调用 vLLM（通过 langextract 库），不经过此客户端

使用示例::

    from app.services.extraction.llm_client import llm_client

    # 生成 JSON（glmocr 线路）
    data = await llm_client.chat_json(
        prompt="请抽取以下化学成分...",
        system_prompt="你是信息抽取助手",
        max_tokens=32768,
    )
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.core.exceptions import BusinessException

logger = get_logger(__name__)


class ExtractionLLMClient:
    """v3 抽取 LLM 客户端（AsyncOpenAI 封装，单例）。

    通过 ``AsyncOpenAI`` 直连 vLLM OpenAI 兼容端点，支持高并发异步调用。
    并发控制由调用方通过 ``asyncio.Semaphore`` 管理（Pipeline 层全局信号量）。

    Attributes:
        _client: AsyncOpenAI 客户端实例。
        _settings: ExtractionSettings 配置访问器。
    """

    _instance: ExtractionLLMClient | None = None

    def __new__(cls) -> ExtractionLLMClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化客户端池（懒加载，首次调用时创建）。"""
        self._clients: dict[tuple, AsyncOpenAI] = {}

    def _ensure_client(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> AsyncOpenAI:
        """确保 AsyncOpenAI 客户端已创建（懒加载，按端点缓存）。

        **无超时设计**：大表格/大批次的 LLM 输出 token 量大（如化学成分 200+ 条
        记录的 JSON），推理时间可能超过 5 分钟。移除超时避免请求被中断重试，
        所有请求压入 vLLM 等待队列，由 ``llm_semaphore`` 控制并发上限。
        仅当通过 ``timeout`` 显式配置时才启用超时。

        Args:
            base_url: OpenAI 兼容端点；None 时使用全局 settings。
            api_key: API Key；None 时使用全局 settings。
            timeout: 请求超时秒数；None 表示无超时（默认）。

        Returns:
            AsyncOpenAI: 对应端点的客户端实例。
        """
        # LLM 端点由调用方从配置解析传入，缺失即报错（不允许 settings/env 兜底）
        if not base_url:
            raise BusinessException("未配置抽取 LLM 端点 base_url")
        api_key = api_key or "EMPTY"  # 本地 vLLM 惯例占位符，非配置回退
        key = (base_url, api_key, timeout)
        if key not in self._clients:
            self._clients[key] = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,  # None=无超时：大输出 token 场景不中断
                max_retries=0,  # 不重试：vLLM 自己处理排队
            )
            logger.info(
                "v3 抽取 LLM 客户端已初始化",
                base_url=base_url,
            )
        return self._clients[key]

    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        endpoint: dict | None = None,
        engine_params: dict | None = None,
    ) -> str:
        """生成文本回复（BaseExtract 线路核心方法）。

        通过 vLLM OpenAI 兼容接口调用，默认使用 BaseExtract 线路参数：
        temperature=0.0、top_p=0.1、enable_thinking=False。

        Args:
            prompt: 用户输入文本（文档内容 + 抽取指令）。
            system_prompt: 可选的系统提示词。
            max_tokens: 生成最大 token 数，默认使用配置项。
            temperature: 采样温度，默认 0.0。
            top_p: top_p 采样，默认 0.1。
            endpoint: KB 专属端点 {base_url, api_key, model}；None 时用全局 settings。
            engine_params: 当前引擎分组参数（top_k / enable_thinking / timeout）。

        Returns:
            str: 模型生成的文本内容。
        """
        base_url = (endpoint or {}).get("base_url")
        api_key = (endpoint or {}).get("api_key")
        model = (endpoint or {}).get("model")
        if not base_url or not model:
            raise BusinessException("未配置抽取 LLM 端点（api_base/model），请在资源与配置中填写")
        # 超时：仅当引擎分组显式配置时启用（默认 None=无超时）
        raw_timeout = (engine_params or {}).get("timeout")
        timeout = float(raw_timeout) if raw_timeout is not None else None
        client = self._ensure_client(base_url=base_url, api_key=api_key, timeout=timeout)

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # BaseExtract 线路 LLM 参数（引擎分组配置，缺失即报错，无 settings/env 兜底）
        _ep = engine_params or {}
        _top_p = top_p if top_p is not None else _ep.get("top_p")
        if _top_p is None:
            raise BusinessException("未配置引擎分组参数 llm.engines.BaseExtract.top_p")
        _top_k = _ep.get("top_k")
        if _top_k is None:
            raise BusinessException("未配置引擎分组参数 llm.engines.BaseExtract.top_k")
        _enable_thinking = _ep.get("enable_thinking")
        if _enable_thinking is None:
            raise BusinessException("未配置引擎分组参数 llm.engines.BaseExtract.enable_thinking")
        if max_tokens is None:
            raise BusinessException("未配置采样 max_tokens（引擎分组 llm.engines.<engine>.max_tokens 或类别级 max_tokens）")
        if temperature is None:
            raise BusinessException("未配置采样温度（引擎分组 llm.engines.<engine>.temperature）")

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=_top_p,
            stream=False,
            extra_body={
                "top_k": _top_k,
                "chat_template_kwargs": {"enable_thinking": _enable_thinking},
            },
        )

        text = response.choices[0].message.content or ""
        # 剥离可能的 thinking 标签（兜底）
        text = self._strip_thinking(text)
        logger.debug(
            "LLM 原始返回",
            extra={"text_len": len(text), "text_preview": text[:300]},
        )
        return text

    async def chat_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        endpoint: dict | None = None,
        engine_params: dict | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """生成 JSON 并解析（BaseExtract 线路 JSON 抽取）。

        调用 ``chat`` 生成文本，随后通过三级容错解析 JSON：
        1. 直接 json.loads
        2. 提取 ```json ... ``` 代码块后解析
        3. 正则定位 {.*} 或 [.*] 后解析

        Args:
            prompt: 用户输入文本。
            system_prompt: 可选的系统提示词。
            max_tokens: 生成最大 token 数。
            temperature: 采样温度。
            endpoint: KB 专属端点；None 时用全局 settings。
            engine_params: 引擎分组参数。

        Returns:
            dict | list: 解析后的 JSON 对象（字典或列表）。

        Raises:
            ValueError: JSON 解析失败时抛出。
        """
        text = await self.chat(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            endpoint=endpoint,
            engine_params=engine_params,
        )
        return self.parse_json(text)

    @staticmethod
    def parse_json(text: str) -> dict[str, Any] | list[dict[str, Any]]:
        """三级容错 JSON 解析（移植自 glm-ocr simple_pipeline）。

        处理策略（按优先级）：
        1. 剥离 markdown 代码块（```json...``` 或 ```...```）
        2. 直接 json.loads
        3. 正则定位首个 { 到末尾 } 或 [ 到 ] 的 JSON 片段再解析
        4. 修复常见 JSON 格式错误后重试（未闭合字符串、尾随逗号）

        Args:
            text: 模型输出的原始文本。

        Returns:
            dict | list: 解析后的 JSON 对象。

        Raises:
            ValueError: 无法解析时抛出。
        """
        cleaned = text.strip()

        # 1. 剥离 markdown 代码块
        fence_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
        match = fence_pattern.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

        # 2. 直接解析
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 3. 正则定位 JSON 对象或数组
        # 尝试 {.*}（贪婪匹配首个 { 至末尾 }）
        obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if obj_match:
            try:
                return json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试 [.*]（JSON 数组）
        arr_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if arr_match:
            try:
                return json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                pass

        # 4. 修复常见 JSON 格式错误
        repaired = ExtractionLLMClient._repair_json(cleaned)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as err:
            logger.error(
                "JSON 解析失败（三级容错均失败）",
                error=str(err),
                raw_output=text[:500],
            )
            raise ValueError(f"无法解析 LLM 输出为 JSON: {err}") from err

    @staticmethod
    def _repair_json(text: str) -> str:
        """修复常见 JSON 格式错误（移植自 simple_pipeline _repair_json）。

        修复项：
        1. 移除尾随逗号（],} 前的逗号）
        2. 修复未闭合的字符串（行尾补充 "）
        3. 移除控制字符

        Args:
            text: 待修复的 JSON 文本。

        Returns:
            str: 修复后的 JSON 文本。
        """
        # 移除尾随逗号
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # 移除控制字符（保留 \n \t）
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return text

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """剥离 Qwen 思考模式的 <think>...</think> 包裹。"""
        pattern = re.compile(r"<think>.*?</think>", re.DOTALL)
        text = pattern.sub("", text)
        return text.strip()


# 模块级单例
llm_client = ExtractionLLMClient()
