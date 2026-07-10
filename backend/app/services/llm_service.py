"""基于 vLLM 的大模型服务封装模块。

本模块封装 vLLM（Very Large Language Model）推理引擎，提供统一的大模型调用接口：
- 模型懒加载：首次调用时才加载模型权重，避免导入阶段占用 GPU 显存
- 异步接口：通过 asyncio.to_thread 将 vLLM 的同步阻塞调用转换为异步接口
- 聊天模板：复用 Qwen3.5 模型自带的 chat_template.jinja 构建对话
- JSON 抽取：从模型输出中解析 JSON（兼容 markdown 代码块包裹的情况）
- 流式输出：以分块方式按 token 增量返回，便于前端流式渲染

注意：
    vLLM 的 LLM 类为同步阻塞 API，本模块通过 asyncio.to_thread 将其放入
    线程池执行，避免阻塞 FastAPI 事件循环。模型加载与推理均在专用线程中进行。

使用示例：
    from app.services.llm_service import llm_service

    # 预热模型（可选，首次调用会自动加载）
    await llm_service.warmup()

    # 生成文本
    text = await llm_service.generate("请总结以下文档：...", system_prompt="你是文档助手")

    # 生成 JSON
    data = await llm_service.generate_json("请抽取文档中的结构化信息：...")
"""

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from typing import Any

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# 默认模型路径（如需切换模型，建议在 settings 中新增配置项后从此读取）
_DEFAULT_MODEL_PATH = "/home/hanson/doc_parse_project/models/Qwen/Qwen3___5-9B"


class LLMService:
    """vLLM 大模型服务封装。

    通过懒加载机制管理 vLLM 的 LLM 实例，提供文本生成、JSON 解析与流式
    输出等能力。所有阻塞调用均通过 asyncio.to_thread 转入线程池执行，
    确保不阻塞事件循环。

    Attributes:
        _model_path: 模型权重所在路径。
        _llm: vLLM 的 LLM 实例，懒加载，首次使用时创建。
        _loaded: 标记模型是否已完成加载。
        _init_kwargs: 传递给 vllm.LLM 的初始化参数。
    """

    def __init__(self, model_path: str, **kwargs: Any) -> None:
        """初始化 LLM 服务，仅保存配置不加载模型。

        Args:
            model_path: HuggingFace 格式模型权重目录路径。
            **kwargs: 传递给 vllm.LLM 的额外初始化参数，覆盖默认值。
        """
        self._model_path: str = model_path
        self._llm: Any = None
        self._loaded: bool = False
        # 默认初始化参数，可被 kwargs 覆盖
        self._init_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "dtype": "float16",
            "gpu_memory_utilization": 0.5,
            "max_model_len": 8192,
            "tensor_parallel_size": 1,
        }
        self._init_kwargs.update(kwargs)

    def _load_model(self) -> None:
        """加载 vLLM 模型实例。

        在首次调用时创建 vllm.LLM 实例并完成模型权重加载与 KV cache 预分配。
        该方法为同步阻塞调用，应由调用方通过 asyncio.to_thread 包装执行。

        Raises:
            BusinessException: 模型加载失败或 GPU 显存不足时抛出。
        """
        if self._loaded:
            return
        logger.info("开始加载 vLLM 模型", model_path=self._model_path)
        try:
            # 延迟导入 vllm，避免模块导入阶段即触发重型依赖初始化
            from vllm import LLM

            self._llm = LLM(model=self._model_path, **self._init_kwargs)
            self._loaded = True
            logger.info("vLLM 模型加载完成", model_path=self._model_path)
        except MemoryError as err:
            # GPU 显存不足会以 MemoryError 或 CUDA OOM 形式抛出
            logger.error("加载模型时显存不足", model_path=self._model_path, error=str(err))
            raise BusinessException(
                code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                message="GPU 显存不足，无法加载大模型，请释放显存后重试",
                details={"model_path": self._model_path, "error": str(err)},
            ) from err
        except Exception as err:
            # 捕获 CUDA OOM 等运行时异常
            if "out of memory" in str(err).lower() or "oom" in str(err).lower():
                logger.error(
                    "加载模型时 CUDA 显存不足",
                    model_path=self._model_path,
                    error=str(err),
                )
                raise BusinessException(
                    code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                    message="GPU 显存不足，无法加载大模型，请释放显存后重试",
                    details={"model_path": self._model_path, "error": str(err)},
                ) from err
            logger.error(
                "加载模型失败",
                model_path=self._model_path,
                error=str(err),
                exc_info=True,
            )
            raise BusinessException(
                code=ErrorCode.SYSTEM_INTERNAL_ERROR,
                message=f"大模型加载失败：{err}",
                details={"model_path": self._model_path},
            ) from err

    def _ensure_loaded(self) -> None:
        """确保模型已加载，未加载时同步加载。

        该方法为同步调用，应通过 asyncio.to_thread 包装后异步调用。
        """
        if not self._loaded:
            self._load_model()

    def _build_messages(
        self, prompt: str, system_prompt: str | None = None
    ) -> list[dict[str, str]]:
        """构建 vLLM chat 接口所需的消息列表。

        遵循 Qwen3.5 chat_template.jinja 的要求：system 消息必须位于首位。
        当未提供 system_prompt 时，仅构造 user 消息。

        Args:
            prompt: 用户输入文本。
            system_prompt: 可选的系统提示词，用于设定模型角色与输出约束。

        Returns:
            list[dict[str, str]]: OpenAI 风格的消息列表，例如
                [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]。
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """同步调用 vLLM chat 接口，返回生成的文本。

        使用 chat_template_kwargs={"enable_thinking": False} 关闭 Qwen3.5 的
        思考模式，使模型直接输出最终答案，避免输出被 <think> 标签包裹。

        Args:
            messages: OpenAI 风格的消息列表。
            max_tokens: 生成最大 token 数。
            temperature: 采样温度，越低输出越确定。

        Returns:
            str: 模型生成的文本内容。

        Raises:
            BusinessException: 推理失败或显存不足时抛出。
        """
        from vllm import SamplingParams

        # 构建采样参数：低温度保证输出稳定性
        sampling_params = SamplingParams(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.9,
        )
        try:
            # use_tqdm=False 关闭进度条，避免污染日志输出
            # enable_thinking=False 关闭思考模式，直接输出答案
            results = self._llm.chat(
                messages,
                sampling_params=sampling_params,
                use_tqdm=False,
                chat_template_kwargs={"enable_thinking": False},
            )
        except Exception as err:
            if "out of memory" in str(err).lower() or "oom" in str(err).lower():
                logger.error("推理时 CUDA 显存不足", error=str(err))
                raise BusinessException(
                    code=ErrorCode.SYSTEM_SERVICE_UNAVAILABLE,
                    message="GPU 显存不足，推理失败，请减少输入长度或释放显存",
                    details={"error": str(err)},
                ) from err
            logger.error("vLLM 推理失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.SYSTEM_INTERNAL_ERROR,
                message=f"大模型推理失败：{err}",
                details={"error": str(err)},
            ) from err

        if not results:
            logger.warning("vLLM 返回空结果")
            return ""

        # RequestOutput.outputs 为 list[CompletionOutput]，取第一个候选
        outputs = results[0].outputs
        if not outputs:
            return ""
        text: str = outputs[0].text
        # 兜底：若模型仍输出了 <think> 块，剥离其中的思考内容，保留正式答案
        text = self._strip_thinking(text)
        return text

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """剥离 Qwen 思考模式的  Tudens... Tudens 包裹。

        当 enable_thinking=False 时模型通常不会输出思考块，但部分场景下
        仍可能包含，此处做兜底清理，仅保留  Tudens 之后的内容。

        处理策略：
        1. 若存在完整的  Tudens... Tudens 思考块（开闭标签齐全），
           移除思考块，保留  Tudens 之后的正式答案
        2. 若仅有  Tudens 开标签但无  Tudens 闭标签（未闭合的思考），
           视为模型输出异常，不强行剥离，原样返回交由下游 _parse_json 处理

        Args:
            text: 原始模型输出文本。

        Returns:
            str: 去除思考块后的文本。
        """
        # 匹配并移除所有完整的 <think>...</think> 思考块（允许跨行）
        # 使用非贪婪匹配 .*? 确保每个思考块独立匹配，支持多个思考块场景
        pattern = re.compile(r"<think>.*?</think>", re.DOTALL)
        text = pattern.sub("", text)
        # 注意：不处理仅含 <think> 而无 </think> 的未闭合情况，
        # 此类异常输出交由 _parse_json 的正则兜底逻辑提取 JSON
        return text.strip()

    async def warmup(self) -> None:
        """预热模型：加载权重并执行一次短促推理。

        在服务启动时调用可提前完成模型加载与 CUDA 内核编译，避免首次
        请求承担加载延迟。该方法幂等，多次调用仅首次实际加载。
        """
        if self._loaded:
            logger.info("模型已加载，跳过预热")
            return
        logger.info("开始模型预热", model_path=self._model_path)
        # 模型加载为重型阻塞操作，交由线程池执行
        await asyncio.to_thread(self._ensure_loaded)
        # 执行一次短推理以触发 kernel 编译与缓存预热
        await asyncio.to_thread(
            self._call_chat,
            self._build_messages("你好"),
            max_tokens=16,
            temperature=0.1,
        )
        logger.info("模型预热完成", model_path=self._model_path)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        """生成文本回复。

        根据用户输入与可选的系统提示词，调用大模型生成文本。低温度
        （默认 0.1）保证输出稳定，适合结构化抽取场景。

        Args:
            prompt: 用户输入文本。
            system_prompt: 可选的系统提示词，用于设定模型角色与输出约束。
            max_tokens: 生成最大 token 数，默认 2048。
            temperature: 采样温度，默认 0.1，越低输出越确定。

        Returns:
            str: 模型生成的文本内容。

        Raises:
            BusinessException: 模型加载或推理失败时抛出。
        """
        # 确保模型已加载
        await asyncio.to_thread(self._ensure_loaded)
        messages = self._build_messages(prompt, system_prompt)
        logger.info(
            "开始生成文本",
            prompt_len=len(prompt),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = await asyncio.to_thread(
            self._call_chat,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        logger.info("文本生成完成", output_len=len(text))
        return text

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
    ) -> dict:
        """生成 JSON 并解析为字典。

        调用 generate() 生成文本，随后从输出中提取并解析 JSON。支持以下
        常见包裹格式：
        - 裸 JSON：{"key": "value"}
        - markdown 代码块：```json\n{...}\n``` 或 ```\n{...}\n```
        - 含前后说明文字的混合输出

        Args:
            prompt: 用户输入文本。
            system_prompt: 可选的系统提示词。
            max_tokens: 生成最大 token 数，默认 2048。

        Returns:
            dict: 解析后的字典对象。

        Raises:
            BusinessException: 生成或 JSON 解析失败时抛出。
        """
        text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        data = self._parse_json(text)
        logger.info("JSON 解析成功", keys=list(data.keys()) if isinstance(data, dict) else None)
        return data

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从模型输出文本中提取并解析 JSON。

        处理策略（按优先级）：
        1. 若文本以 markdown 代码块包裹（```json...``` 或 ```...```），
           提取代码块内容
        2. 尝试直接 json.loads
        3. 使用正则定位首个 { 到末尾 } 的 JSON 片段再解析
        4. 上述均失败时抛出 BusinessException

        Args:
            text: 模型输出的原始文本。

        Returns:
            dict: 解析后的字典对象。

        Raises:
            BusinessException: 无法从输出中解析出合法 JSON 时抛出。
        """
        cleaned = text.strip()

        # 1. 剥离 markdown 代码块
        # 匹配 ```json\n...\n``` 或 ```\n...\n```
        fence_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
        match = fence_pattern.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

        # 2. 尝试直接解析
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
            # 若解析出非字典（如列表），包装为字典返回
            if isinstance(result, list):
                return {"items": result}
            return {"value": result}
        except json.JSONDecodeError:
            pass

        # 3. 正则定位首个 JSON 对象（{ 到 }）
        # 贪婪匹配首个 { 至末尾的 }，处理嵌套结构
        obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if obj_match:
            candidate = obj_match.group(0)
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
                if isinstance(result, list):
                    return {"items": result}
                return {"value": result}
            except json.JSONDecodeError:
                pass

        # 4. 解析失败
        logger.error("JSON 解析失败", raw_output=text[:500])
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="无法从模型输出中解析出合法 JSON",
            details={"raw_output": text[:500]},
        )

    async def stream_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        chunk_size: int = 4,
    ) -> AsyncGenerator[str, None]:
        """以流式方式生成文本，按 chunk 增量返回。

        由于当前 vLLM 的 LLM.chat() 为同步阻塞 API 且不支持原生 token 流式
        输出，本方法采用「先生成后分块」的策略：先调用 generate() 获取
        完整输出，再按 chunk_size 个字符切分，逐块 yield，模拟流式效果。
        每个 chunk 之间插入极短的 asyncio.sleep，让出事件循环控制权。

        当 vLLM 升级支持原生流式输出后，可改为基于 vLLM streaming
        callback 的实现，无需改动调用方代码。

        Args:
            prompt: 用户输入文本。
            system_prompt: 可选的系统提示词。
            max_tokens: 生成最大 token 数，默认 2048。
            temperature: 采样温度，默认 0.1。
            chunk_size: 每个 chunk 包含的字符数，默认 4。

        Yields:
            str: 文本分片，调用方应累加拼接为完整输出。
        """
        # 先生成完整输出
        full_text = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # 按 chunk_size 切分并逐块 yield
        for i in range(0, len(full_text), chunk_size):
            yield full_text[i : i + chunk_size]
            # 让出事件循环，模拟流式节奏
            await asyncio.sleep(0)


# 模块级单例：
# 使用硬编码模型路径创建单例实例，便于全局复用。
# TODO: 建议在 settings 中新增 LLM_MODEL_PATH 配置项后替换此处的硬编码路径。
llm_service = LLMService(model_path=_DEFAULT_MODEL_PATH)
