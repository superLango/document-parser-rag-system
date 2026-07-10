"""结构化信息抽取服务测试模块。

测试 ExtractionService 的核心功能：
- extract()：基于 schema 从文本中抽取结构化字段
- _build_extraction_prompt()：提示词构造
- _validate_extraction()：必填字段校验
- extract_batch()：批量抽取

所有测试通过 mock LLMService 避免真实模型调用，确保可在无 GPU 环境运行。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessException
from app.services.extraction_service import ExtractionService


# ---------------------------------------------------------------
# 测试用 schema 与文本数据
# ---------------------------------------------------------------
_SIMPLE_SCHEMA = {
    "fields": [
        {
            "name": "材料名称",
            "type": "string",
            "description": "材料的标准名称",
            "required": True,
        }
    ]
}

_MULTI_FIELD_SCHEMA = {
    "fields": [
        {
            "name": "材料名称",
            "type": "string",
            "description": "材料的标准名称",
            "required": True,
        },
        {
            "name": "规格型号",
            "type": "string",
            "description": "规格与型号信息",
            "required": False,
        },
        {
            "name": "数量",
            "type": "number",
            "description": "数量值",
            "required": True,
        },
    ]
}

_SAMPLE_TEXT = "本工程使用不锈钢材料，规格型号为 304，数量 100 吨。"


@pytest.fixture
def mock_llm():
    """创建 mock LLMService 实例。

    generate_json 默认返回空字典，各测试可按需覆盖 return_value。
    """
    llm = MagicMock()
    llm.generate_json = AsyncMock(return_value={})
    llm.generate = AsyncMock(return_value="")
    return llm


@pytest.fixture
def extraction_service(mock_llm):
    """创建使用 mock LLM 的 ExtractionService 实例。"""
    return ExtractionService(llm=mock_llm)


# ---------------------------------------------------------------
# extract() 测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_extract_simple_schema(extraction_service, mock_llm):
    """测试使用简单 schema 抽取文本。

    Mock llm.generate_json 返回 {"材料名称": "不锈钢"}，
    验证抽取结果正确返回且 generate_json 被调用一次。
    """
    mock_llm.generate_json.return_value = {"材料名称": "不锈钢"}

    result = await extraction_service.extract(_SAMPLE_TEXT, _SIMPLE_SCHEMA)

    assert result == {"材料名称": "不锈钢"}
    mock_llm.generate_json.assert_awaited_once()
    # 验证传入了系统提示词
    call_kwargs = mock_llm.generate_json.call_args
    assert "system_prompt" in call_kwargs.kwargs


@pytest.mark.asyncio
async def test_extract_empty_text_raises(extraction_service):
    """测试空文本抽取时抛出 BusinessException。

    空字符串和纯空白字符串均应被拒绝。
    """
    # 空字符串
    with pytest.raises(BusinessException) as exc_info:
        await extraction_service.extract("", _SIMPLE_SCHEMA)
    assert "不能为空" in exc_info.value.message

    # 纯空白字符串
    with pytest.raises(BusinessException):
        await extraction_service.extract("   \n  ", _SIMPLE_SCHEMA)


@pytest.mark.asyncio
async def test_extract_invalid_schema_raises(extraction_service):
    """测试无效 schema_definition 格式时抛出 BusinessException。"""
    # 非 dict 类型
    with pytest.raises(BusinessException):
        await extraction_service.extract(_SAMPLE_TEXT, "not a dict")  # type: ignore[arg-type]

    # 缺少 fields 键
    with pytest.raises(BusinessException):
        await extraction_service.extract(_SAMPLE_TEXT, {"no_fields": []})

    # fields 非 list 类型
    with pytest.raises(BusinessException):
        await extraction_service.extract(_SAMPLE_TEXT, {"fields": "not a list"})


@pytest.mark.asyncio
async def test_extract_multi_fields(extraction_service, mock_llm):
    """测试多字段 schema 的抽取。

    Mock 返回所有字段值，验证结果完整。
    """
    mock_llm.generate_json.return_value = {
        "材料名称": "不锈钢",
        "规格型号": "304",
        "数量": 100,
    }

    result = await extraction_service.extract(_SAMPLE_TEXT, _MULTI_FIELD_SCHEMA)

    assert result["材料名称"] == "不锈钢"
    assert result["规格型号"] == "304"
    assert result["数量"] == 100


@pytest.mark.asyncio
async def test_extract_missing_required_field(extraction_service, mock_llm):
    """测试必填字段缺失时不阻断返回（记录警告但返回已抽取数据）。"""
    # 返回的数据缺少必填字段 "数量"
    mock_llm.generate_json.return_value = {
        "材料名称": "不锈钢",
        "规格型号": "304",
    }

    result = await extraction_service.extract(_SAMPLE_TEXT, _MULTI_FIELD_SCHEMA)

    # 仍返回已抽取的数据
    assert result["材料名称"] == "不锈钢"
    # 缺失的必填字段不在结果中
    assert "数量" not in result or result.get("数量") is None


@pytest.mark.asyncio
async def test_extract_llm_failure_raises(extraction_service, mock_llm):
    """测试 LLM 调用异常时抛出 BusinessException。"""
    mock_llm.generate_json.side_effect = BusinessException(
        message="LLM 推理失败"
    )

    with pytest.raises(BusinessException):
        await extraction_service.extract(_SAMPLE_TEXT, _SIMPLE_SCHEMA)


# ---------------------------------------------------------------
# _build_extraction_prompt() 测试
# ---------------------------------------------------------------
def test_build_extraction_prompt_includes_field_names(extraction_service):
    """测试提示词中包含字段名。"""
    prompt = extraction_service._build_extraction_prompt(
        _SAMPLE_TEXT, _MULTI_FIELD_SCHEMA
    )

    assert "材料名称" in prompt
    assert "规格型号" in prompt
    assert "数量" in prompt


def test_build_extraction_prompt_includes_descriptions(extraction_service):
    """测试提示词中包含字段描述。"""
    prompt = extraction_service._build_extraction_prompt(
        _SAMPLE_TEXT, _MULTI_FIELD_SCHEMA
    )

    assert "材料的标准名称" in prompt
    assert "规格与型号信息" in prompt
    assert "数量值" in prompt


def test_build_extraction_prompt_includes_required_label(extraction_service):
    """测试提示词中包含必填/选填标记。"""
    prompt = extraction_service._build_extraction_prompt(
        _SAMPLE_TEXT, _MULTI_FIELD_SCHEMA
    )

    assert "必填" in prompt
    assert "选填" in prompt


def test_build_extraction_prompt_includes_text(extraction_service):
    """测试提示词中包含待抽取文本。"""
    prompt = extraction_service._build_extraction_prompt(
        _SAMPLE_TEXT, _SIMPLE_SCHEMA
    )

    assert _SAMPLE_TEXT in prompt


def test_build_extraction_prompt_includes_json_example(extraction_service):
    """测试提示词中包含 JSON 输出示例。"""
    prompt = extraction_service._build_extraction_prompt(
        _SAMPLE_TEXT, _SIMPLE_SCHEMA
    )

    # 示例中应包含字段名作为键
    assert "材料名称" in prompt
    # 应包含 JSON 格式标记
    assert "{" in prompt
    assert "}" in prompt


# ---------------------------------------------------------------
# _validate_extraction() 测试
# ---------------------------------------------------------------
def test_validate_extraction_all_present(extraction_service):
    """测试所有必填字段均存在时返回空列表。"""
    data = {"材料名称": "不锈钢", "数量": 100}
    missing = extraction_service._validate_extraction(data, _MULTI_FIELD_SCHEMA)

    assert missing == []


def test_validate_extraction_missing_required(extraction_service):
    """测试缺少必填字段时返回缺失字段名列表。"""
    data = {"材料名称": "不锈钢"}  # 缺少必填字段 "数量"
    missing = extraction_service._validate_extraction(data, _MULTI_FIELD_SCHEMA)

    assert "数量" in missing
    assert "材料名称" not in missing


def test_validate_extraction_null_value(extraction_service):
    """测试必填字段值为 None 时视为缺失。"""
    data = {"材料名称": "不锈钢", "数量": None}
    missing = extraction_service._validate_extraction(data, _MULTI_FIELD_SCHEMA)

    assert "数量" in missing


def test_validate_extraction_optional_missing_ok(extraction_service):
    """测试选填字段缺失不影响校验结果。"""
    data = {"材料名称": "不锈钢", "数量": 100}  # 缺少选填字段 "规格型号"
    missing = extraction_service._validate_extraction(data, _MULTI_FIELD_SCHEMA)

    assert missing == []


def test_validate_extraction_empty_schema(extraction_service):
    """测试空 schema 时无缺失字段。"""
    data = {}
    missing = extraction_service._validate_extraction(data, {"fields": []})

    assert missing == []


# ---------------------------------------------------------------
# extract_batch() 测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_extract_batch_multiple_texts(extraction_service, mock_llm):
    """测试批量抽取多段文本。

    Mock LLM 对不同文本返回不同结果，验证返回列表顺序与输入一致。
    """
    texts = [
        "材料为不锈钢",
        "材料为碳钢",
        "材料为铝合金",
    ]
    mock_llm.generate_json.side_effect = [
        {"材料名称": "不锈钢"},
        {"材料名称": "碳钢"},
        {"材料名称": "铝合金"},
    ]

    results = await extraction_service.extract_batch(texts, _SIMPLE_SCHEMA)

    assert len(results) == 3
    assert results[0] == {"材料名称": "不锈钢"}
    assert results[1] == {"材料名称": "碳钢"}
    assert results[2] == {"材料名称": "铝合金"}


@pytest.mark.asyncio
async def test_extract_batch_empty_list(extraction_service):
    """测试空列表输入返回空列表。"""
    results = await extraction_service.extract_batch([], _SIMPLE_SCHEMA)

    assert results == []


@pytest.mark.asyncio
async def test_extract_batch_partial_failure(extraction_service, mock_llm):
    """测试批量抽取中部分失败时对应位置返回空字典。

    第二段文本触发 LLM 异常，应返回空字典而不中断其他抽取。
    """
    texts = ["正常文本", "异常文本", "正常文本2"]
    mock_llm.generate_json.side_effect = [
        {"材料名称": "不锈钢"},
        BusinessException(message="LLM 推理失败"),
        {"材料名称": "铝合金"},
    ]

    results = await extraction_service.extract_batch(texts, _SIMPLE_SCHEMA)

    assert len(results) == 3
    assert results[0] == {"材料名称": "不锈钢"}
    assert results[1] == {}  # 失败位置返回空字典
    assert results[2] == {"材料名称": "铝合金"}
