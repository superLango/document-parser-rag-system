"""知识图谱抽取服务测试模块。

测试 GraphExtractService 的核心功能：
- Entity / Relation / ExtractionResult 数据模型
- extract()：基于 LLM 的实体关系抽取（DeepKE 回退路径）
- _extract_with_deepke()：DeepKE 抽取路径
- extract_batch()：批量抽取
- 错误处理：空文本、LLM 失败、解析异常
- DeepKE 回退：DeepKE 不可用时自动回退到 LLM

所有测试通过 mock 避免真实模型调用，确保可在无 GPU 环境运行。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessException
from app.services.graph_extract_service import (
    Entity,
    ExtractionResult,
    GraphExtractService,
    Relation,
)


# ---------------------------------------------------------------
# 数据模型测试
# ---------------------------------------------------------------
class TestModels:
    """Entity / Relation / ExtractionResult 模型测试。"""

    def test_entity_default_offsets(self):
        """测试 Entity 未提供偏移时默认为 0。"""
        entity = Entity(text="Q235钢材", type="材料")

        assert entity.text == "Q235钢材"
        assert entity.type == "材料"
        assert entity.start == 0
        assert entity.end == 0

    def test_entity_with_offsets(self):
        """测试 Entity 带偏移时正确存储。"""
        entity = Entity(text="Q235", type="材料", start=10, end=14)

        assert entity.start == 10
        assert entity.end == 14

    def test_relation_fields(self):
        """测试 Relation 三个字段正确存储。"""
        relation = Relation(head="Q235钢材", relation="执行标准", tail="GB/T700")

        assert relation.head == "Q235钢材"
        assert relation.relation == "执行标准"
        assert relation.tail == "GB/T700"

    def test_extraction_result_defaults_empty(self):
        """测试 ExtractionResult 默认为空列表。"""
        result = ExtractionResult()

        assert result.entities == []
        assert result.relations == []

    def test_extraction_result_with_data(self):
        """测试 ExtractionResult 正确携带实体与关系。"""
        entities = [Entity(text="Q235", type="材料")]
        relations = [Relation(head="Q235", relation="材质", tail="钢材")]
        result = ExtractionResult(entities=entities, relations=relations)

        assert len(result.entities) == 1
        assert len(result.relations) == 1
        assert result.entities[0].text == "Q235"
        assert result.relations[0].relation == "材质"


# ---------------------------------------------------------------
# 测试辅助：单例状态管理
# ---------------------------------------------------------------
@pytest.fixture
def reset_singleton():
    """重置单例状态，确保测试间隔离。

    保存原始类属性，重置为未初始化状态供各测试配置，
    测试完成后恢复原始状态。
    """
    cls = GraphExtractService
    saved = {
        "_instance": cls._instance,
        "_deepke_model": cls._deepke_model,
        "_use_deepke": cls._use_deepke,
        "_initialized": cls._initialized,
    }
    # 重置为未初始化状态
    cls._instance = None
    cls._deepke_model = None
    cls._use_deepke = False
    cls._initialized = False
    yield cls
    # 恢复原始状态
    cls._instance = saved["_instance"]
    cls._deepke_model = saved["_deepke_model"]
    cls._use_deepke = saved["_use_deepke"]
    cls._initialized = saved["_initialized"]


@pytest.fixture
def llm_service(reset_singleton, monkeypatch):
    """创建使用 LLM 后端的服务实例，并 mock llm_service.generate_json。

    DeepKE 未安装时 _init_model 会自动设置 _use_deepke=False，
    因此实例化后即为 LLM 模式。
    """
    service = GraphExtractService()
    assert service._use_deepke is False

    # mock llm_service.generate_json，避免真实模型调用
    from app.services import llm_service as llm_module

    mock_generate = AsyncMock()
    monkeypatch.setattr(llm_module.llm_service, "generate_json", mock_generate)
    return service, mock_generate


# ---------------------------------------------------------------
# LLM 抽取测试（DeepKE 不可用时的回退路径）
# ---------------------------------------------------------------
class TestLLMExtraction:
    """_extract_with_llm 方法测试。"""

    @pytest.mark.asyncio
    async def test_extract_llm_success(self, llm_service):
        """测试 LLM 抽取成功返回实体与关系。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {
            "entities": [
                {"text": "Q235钢材", "type": "材料"},
                {"text": "GB/T700", "type": "标准"},
            ],
            "relations": [
                {"head": "Q235钢材", "relation": "执行标准", "tail": "GB/T700"},
            ],
        }

        result = await service.extract("本工程使用Q235钢材，执行GB/T700标准。")

        assert len(result.entities) == 2
        assert result.entities[0].text == "Q235钢材"
        assert result.entities[0].type == "材料"
        assert result.entities[1].text == "GB/T700"
        assert result.entities[1].type == "标准"
        assert len(result.relations) == 1
        assert result.relations[0].head == "Q235钢材"
        assert result.relations[0].relation == "执行标准"
        assert result.relations[0].tail == "GB/T700"
        mock_generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_llm_empty_response(self, llm_service):
        """测试 LLM 返回空实体与关系时返回空结果。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {"entities": [], "relations": []}

        result = await service.extract("无实体关系的文本")

        assert result.entities == []
        assert result.relations == []

    @pytest.mark.asyncio
    async def test_extract_llm_missing_keys(self, llm_service):
        """测试 LLM 返回缺少 entities/relations 键时返回空结果。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {"other": "data"}

        result = await service.extract("测试文本")

        assert result.entities == []
        assert result.relations == []

    @pytest.mark.asyncio
    async def test_extract_llm_skips_invalid_entity(self, llm_service):
        """测试 LLM 返回的非法实体条目被跳过。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {
            "entities": [
                {"text": "Q235", "type": "材料"},
                {"text": "缺类型"},  # 缺少 type 字段，应跳过
                "非字典条目",  # 非字典，应跳过
            ],
            "relations": [],
        }

        result = await service.extract("Q235 材料")

        assert len(result.entities) == 1
        assert result.entities[0].text == "Q235"

    @pytest.mark.asyncio
    async def test_extract_llm_skips_invalid_relation(self, llm_service):
        """测试 LLM 返回的非法关系条目被跳过。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {
            "entities": [],
            "relations": [
                {"head": "Q235", "relation": "执行标准", "tail": "GB/T700"},
                {"head": "缺尾实体", "relation": "用于"},  # 缺少 tail，应跳过
            ],
        }

        result = await service.extract("Q235 执行 GB/T700")

        assert len(result.relations) == 1
        assert result.relations[0].head == "Q235"

    @pytest.mark.asyncio
    async def test_extract_llm_truncates_long_text(self, llm_service):
        """测试超长文本被截断后传入 LLM。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {"entities": [], "relations": []}
        long_text = "A" * 3000  # 超过 _MAX_LLM_TEXT_LEN=2000

        await service.extract(long_text)

        # 验证传入 generate_json 的提示词中文本已被截断
        prompt = mock_generate.call_args[0][0]
        # 原始 3000 个 A 不应完整出现，截断后仅 2000 个
        assert "A" * 2000 in prompt
        assert "A" * 2001 not in prompt

    @pytest.mark.asyncio
    async def test_extract_llm_failure_raises(self, llm_service):
        """测试 LLM 调用失败时抛出 BusinessException。"""
        service, mock_generate = llm_service
        mock_generate.side_effect = RuntimeError("模型推理失败")

        with pytest.raises(BusinessException) as exc_info:
            await service.extract("测试文本")

        assert "LLM 知识抽取失败" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_extract_llm_business_exception_propagates(self, llm_service):
        """测试 LLM 抛出 BusinessException 时原样向上传播。"""
        service, mock_generate = llm_service
        mock_generate.side_effect = BusinessException(
            message="JSON 解析失败",
            code=40001,
        )

        with pytest.raises(BusinessException) as exc_info:
            await service.extract("测试文本")

        assert exc_info.value.message == "JSON 解析失败"


# ---------------------------------------------------------------
# 空文本校验测试
# ---------------------------------------------------------------
class TestValidation:
    """extract 方法的输入校验测试。"""

    @pytest.mark.asyncio
    async def test_extract_empty_text_raises(self, llm_service):
        """测试空文本抽取时抛出 BusinessException。"""
        service, _ = llm_service

        with pytest.raises(BusinessException) as exc_info:
            await service.extract("")

        assert "不能为空" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_extract_whitespace_text_raises(self, llm_service):
        """测试纯空白文本抽取时抛出 BusinessException。"""
        service, _ = llm_service

        with pytest.raises(BusinessException):
            await service.extract("   \n  \t  ")


# ---------------------------------------------------------------
# DeepKE 抽取路径测试
# ---------------------------------------------------------------
@pytest.fixture
def deepke_service(reset_singleton):
    """创建使用 DeepKE 后端的服务实例，模型为 mock 对象。

    手动设置 _use_deepke=True 并注入 mock 模型，
    模拟 DeepKE 成功加载的场景。
    """
    service = GraphExtractService()
    # 手动切换为 DeepKE 模式
    service._use_deepke = True
    service._deepke_model = MagicMock()
    return service


class TestDeepKEExtraction:
    """_extract_with_deepke 方法测试。"""

    @pytest.mark.asyncio
    async def test_deepke_extract_success(self, deepke_service):
        """测试 DeepKE 抽取成功返回实体与关系。"""
        service = deepke_service
        service._deepke_model.predict_entities.return_value = [
            {"text": "Q235", "type": "材料", "start": 0, "end": 4},
        ]
        service._deepke_model.predict_relations.return_value = [
            {"head": "Q235", "relation": "材质", "tail": "钢材"},
        ]

        result = await service.extract("Q235钢材")

        assert len(result.entities) == 1
        assert result.entities[0].text == "Q235"
        assert result.entities[0].start == 0
        assert result.entities[0].end == 4
        assert len(result.relations) == 1
        assert result.relations[0].relation == "材质"
        service._deepke_model.predict_entities.assert_called_once_with("Q235钢材")
        service._deepke_model.predict_relations.assert_called_once_with("Q235钢材")

    @pytest.mark.asyncio
    async def test_deepke_extract_empty_results(self, deepke_service):
        """测试 DeepKE 返回空结果时返回空 ExtractionResult。"""
        service = deepke_service
        service._deepke_model.predict_entities.return_value = []
        service._deepke_model.predict_relations.return_value = []

        result = await service.extract("无实体文本")

        assert result.entities == []
        assert result.relations == []

    @pytest.mark.asyncio
    async def test_deepke_extract_failure_raises(self, deepke_service):
        """测试 DeepKE 推理失败时抛出 BusinessException。"""
        service = deepke_service
        service._deepke_model.predict_entities.side_effect = RuntimeError("模型加载错误")

        with pytest.raises(BusinessException) as exc_info:
            await service.extract("测试文本")

        assert "DeepKE 抽取失败" in exc_info.value.message


# ---------------------------------------------------------------
# 批量抽取测试
# ---------------------------------------------------------------
class TestBatchExtraction:
    """extract_batch 方法测试。"""

    @pytest.mark.asyncio
    async def test_batch_extract_multiple_texts(self, llm_service):
        """测试批量抽取多段文本，结果顺序与输入一致。"""
        service, mock_generate = llm_service

        def _side_effect(prompt):
            if "不锈钢" in prompt:
                return {"entities": [{"text": "不锈钢", "type": "材料"}], "relations": []}
            if "碳钢" in prompt:
                return {"entities": [{"text": "碳钢", "type": "材料"}], "relations": []}
            return {"entities": [], "relations": []}

        mock_generate.side_effect = AsyncMock(side_effect=_side_effect)

        results = await service.extract_batch(["不锈钢材料", "碳钢材料", "无实体文本"])

        assert len(results) == 3
        assert results[0].entities[0].text == "不锈钢"
        assert results[1].entities[0].text == "碳钢"
        assert results[2].entities == []

    @pytest.mark.asyncio
    async def test_batch_extract_empty_list(self, llm_service):
        """测试空列表输入返回空列表。"""
        service, _ = llm_service

        results = await service.extract_batch([])

        assert results == []

    @pytest.mark.asyncio
    async def test_batch_extract_partial_failure(self, llm_service):
        """测试批量抽取中部分失败时对应位置返回空结果。

        包含 "异常" 的文本触发 generate_json 抛出异常，
        应返回空 ExtractionResult 而不中断其他抽取。
        """
        service, mock_generate = llm_service

        async def _side_effect(prompt):
            # 基于提示词内容判断是否失败，避免并发执行顺序不确定
            if "异常文本" in prompt:
                raise RuntimeError("模型推理失败")
            return {"entities": [{"text": "正常", "type": "材料"}], "relations": []}

        mock_generate.side_effect = _side_effect

        results = await service.extract_batch(["正常文本", "异常文本", "也正常"])

        assert len(results) == 3
        assert len(results[0].entities) == 1  # 成功
        assert results[1].entities == []  # 失败位置返回空
        assert len(results[2].entities) == 1  # 成功

    @pytest.mark.asyncio
    async def test_batch_extract_empty_text_in_batch(self, llm_service):
        """测试批量中包含空文本时该位置返回空结果而非中断。"""
        service, mock_generate = llm_service
        mock_generate.return_value = {"entities": [], "relations": []}

        results = await service.extract_batch(["正常文本", "", "也正常"])

        assert len(results) == 3
        # 空文本位置返回空 ExtractionResult
        assert results[1].entities == []
        assert results[1].relations == []


# ---------------------------------------------------------------
# DeepKE 回退到 LLM 测试
# ---------------------------------------------------------------
class TestDeepKEFallback:
    """DeepKE 不可用时回退到 LLM 的测试。"""

    def test_deepke_unavailable_falls_back_to_llm(self, reset_singleton, monkeypatch):
        """测试 DeepKE 导入失败时自动回退到 LLM 模式。

        DeepKE 未安装时，_init_model 应捕获 ImportError，
        设置 _use_deepke=False 并标记 _initialized=True。
        """
        service = GraphExtractService()

        assert service._use_deepke is False
        assert service._deepke_model is None
        assert service._initialized is True

    def test_deepke_init_failure_falls_back_to_llm(self, reset_singleton, monkeypatch):
        """测试 DeepKE 导入成功但初始化异常时回退到 LLM。

        通过 mock deepke.DeepKE 抛出异常模拟权重加载失败，
        验证服务仍能以 LLM 模式初始化。
        """
        # 在 sys.modules 中注入 mock 的 deepke 模块
        import sys

        mock_deepke_module = MagicMock()
        mock_deepke_module.DeepKE.side_effect = RuntimeError("权重文件缺失")
        monkeypatch.setitem(sys.modules, "deepke", mock_deepke_module)

        service = GraphExtractService()

        assert service._use_deepke is False
        assert service._deepke_model is None
        assert service._initialized is True
        mock_deepke_module.DeepKE.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_llm_works(self, reset_singleton, monkeypatch):
        """测试回退到 LLM 后抽取功能正常工作。"""
        service = GraphExtractService()
        assert service._use_deepke is False

        from app.services import llm_service as llm_module

        mock_generate = AsyncMock(
            return_value={
                "entities": [{"text": "Q345", "type": "材料"}],
                "relations": [],
            }
        )
        monkeypatch.setattr(llm_module.llm_service, "generate_json", mock_generate)

        result = await service.extract("Q345是低合金高强度钢")

        assert len(result.entities) == 1
        assert result.entities[0].text == "Q345"


# ---------------------------------------------------------------
# 提示词构造测试
# ---------------------------------------------------------------
class TestPromptBuilding:
    """_build_llm_prompt 方法测试。"""

    def test_prompt_contains_entity_types(self):
        """测试提示词中包含实体类型说明。"""
        prompt = GraphExtractService._build_llm_prompt("测试文本")

        assert "材料" in prompt
        assert "标准" in prompt
        assert "工艺" in prompt
        assert "参数" in prompt

    def test_prompt_contains_relation_types(self):
        """测试提示词中包含关系类型说明。"""
        prompt = GraphExtractService._build_llm_prompt("测试文本")

        assert "执行标准" in prompt
        assert "材质" in prompt
        assert "用于" in prompt
        assert "包含" in prompt

    def test_prompt_contains_text(self):
        """测试提示词中包含待抽取文本。"""
        prompt = GraphExtractService._build_llm_prompt("Q235钢材执行GB/T700")

        assert "Q235钢材执行GB/T700" in prompt

    def test_prompt_contains_json_format(self):
        """测试提示词中包含 JSON 格式说明。"""
        prompt = GraphExtractService._build_llm_prompt("测试")

        assert "entities" in prompt
        assert "relations" in prompt
        assert "JSON" in prompt
