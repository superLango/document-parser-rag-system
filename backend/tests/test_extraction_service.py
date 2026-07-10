"""结构化信息抽取服务测试模块。

测试 ExtractionService 的核心功能：
- extract()：基于 schema 从文本中抽取结构化字段
- _build_examples()：few-shot 示例构造
- _build_prompt_description()：提示描述构造
- _validate_extraction()：必填字段校验
- extract_batch()：批量抽取

所有测试通过 mock langextract.extract 避免真实模型调用，确保可在无 GPU 环境运行。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import langextract
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


def _make_annotated_document(extractions_data: dict[str, str]):
    """构造模拟的 AnnotatedDocument 结果。

    Args:
        extractions_data: 字段名到字段值的映射。

    Returns:
        SimpleNamespace: 模拟的 AnnotatedDocument，含 extractions 列表。
    """
    extractions = [
        SimpleNamespace(extraction_class=k, extraction_text=v)
        for k, v in extractions_data.items()
    ]
    return SimpleNamespace(extractions=extractions)


@pytest.fixture
def mock_extract(monkeypatch):
    """Mock langextract.extract，默认返回空 extractions。

    各测试可按需覆盖 return_value 或 side_effect。
    """
    mock = MagicMock(return_value=_make_annotated_document({}))
    monkeypatch.setattr(langextract, "extract", mock)
    return mock


@pytest.fixture
def extraction_service():
    """创建 ExtractionService 实例。

    ModelConfig 仅保存配置不建立连接，可安全在测试环境中实例化。
    """
    return ExtractionService()


# ---------------------------------------------------------------
# extract() 测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_extract_simple_schema(extraction_service, mock_extract):
    """测试使用简单 schema 抽取文本。

    Mock langextract.extract 返回包含 "材料名称" 的 AnnotatedDocument，
    验证抽取结果正确返回且 langextract.extract 被调用一次。
    """
    mock_extract.return_value = _make_annotated_document({"材料名称": "不锈钢"})

    result = await extraction_service.extract(_SAMPLE_TEXT, _SIMPLE_SCHEMA)

    assert result == {"材料名称": "不锈钢"}
    mock_extract.assert_called_once()
    # 验证传入了 prompt_description 与 examples 关键字参数
    call_kwargs = mock_extract.call_args.kwargs
    assert "prompt_description" in call_kwargs
    assert "examples" in call_kwargs


@pytest.mark.asyncio
async def test_extract_empty_text_raises(extraction_service, mock_extract):
    """测试空文本抽取时抛出 BusinessException。

    空字符串和纯空白字符串均应被拒绝，且不应调用 langextract.extract。
    """
    # 空字符串
    with pytest.raises(BusinessException) as exc_info:
        await extraction_service.extract("", _SIMPLE_SCHEMA)
    assert "不能为空" in exc_info.value.message

    # 纯空白字符串
    with pytest.raises(BusinessException):
        await extraction_service.extract("   \n  ", _SIMPLE_SCHEMA)

    # 校验未触发模型调用
    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_extract_invalid_schema_raises(extraction_service, mock_extract):
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
async def test_extract_multi_fields(extraction_service, mock_extract):
    """测试多字段 schema 的抽取。

    Mock 返回所有字段值，验证结果完整。
    """
    mock_extract.return_value = _make_annotated_document(
        {"材料名称": "不锈钢", "规格型号": "304", "数量": "100"}
    )

    result = await extraction_service.extract(_SAMPLE_TEXT, _MULTI_FIELD_SCHEMA)

    assert result["材料名称"] == "不锈钢"
    assert result["规格型号"] == "304"
    assert result["数量"] == "100"


@pytest.mark.asyncio
async def test_extract_missing_required_field(extraction_service, mock_extract):
    """测试必填字段缺失时不阻断返回（记录警告但返回已抽取数据）。"""
    # 返回的数据缺少必填字段 "数量"
    mock_extract.return_value = _make_annotated_document(
        {"材料名称": "不锈钢", "规格型号": "304"}
    )

    result = await extraction_service.extract(_SAMPLE_TEXT, _MULTI_FIELD_SCHEMA)

    # 仍返回已抽取的数据
    assert result["材料名称"] == "不锈钢"
    # 缺失的必填字段不在结果中
    assert "数量" not in result or result.get("数量") is None


@pytest.mark.asyncio
async def test_extract_none_extractions(extraction_service, mock_extract):
    """测试 result.extractions 为 None 时返回空字典。"""
    mock_extract.return_value = SimpleNamespace(extractions=None)

    result = await extraction_service.extract(_SAMPLE_TEXT, _SIMPLE_SCHEMA)

    assert result == {}


@pytest.mark.asyncio
async def test_extract_llm_failure_raises(extraction_service, mock_extract):
    """测试 langextract.extract 抛出异常时转换为 BusinessException。"""
    mock_extract.side_effect = RuntimeError("模型推理失败")

    with pytest.raises(BusinessException):
        await extraction_service.extract(_SAMPLE_TEXT, _SIMPLE_SCHEMA)


# ---------------------------------------------------------------
# _build_examples() 测试
# ---------------------------------------------------------------
def test_build_examples_generates_example_data(extraction_service):
    """测试 _build_examples 生成 ExampleData 列表。"""
    examples = extraction_service._build_examples(_MULTI_FIELD_SCHEMA)

    assert len(examples) == 1
    example = examples[0]
    # 示例文本非空
    assert example.text
    # 每个字段对应一个 Extraction
    assert len(example.extractions) == 3


def test_build_examples_uses_field_names_as_extraction_class(extraction_service):
    """测试 Extraction 的 extraction_class 与字段名一致。"""
    examples = extraction_service._build_examples(_MULTI_FIELD_SCHEMA)

    example = examples[0]
    extraction_classes = {ext.extraction_class for ext in example.extractions}
    assert extraction_classes == {"材料名称", "规格型号", "数量"}


def test_build_examples_includes_sample_text(extraction_service):
    """测试示例文本中包含字段名与示例值。"""
    examples = extraction_service._build_examples(_SIMPLE_SCHEMA)

    example = examples[0]
    assert "材料名称" in example.text
    # string 类型字段的示例值前缀
    assert "示例材料名称" in example.text


def test_build_examples_number_field(extraction_service):
    """测试 number 类型字段生成数字示例值。"""
    examples = extraction_service._build_examples(_MULTI_FIELD_SCHEMA)

    example = examples[0]
    number_ext = next(
        ext for ext in example.extractions if ext.extraction_class == "数量"
    )
    assert number_ext.extraction_text == "100"


def test_build_examples_empty_schema(extraction_service):
    """测试空 schema 时返回空列表。"""
    examples = extraction_service._build_examples({"fields": []})

    assert examples == []


# ---------------------------------------------------------------
# _build_prompt_description() 测试
# ---------------------------------------------------------------
def test_build_prompt_description_includes_field_names(extraction_service):
    """测试提示描述中包含字段名。"""
    prompt = extraction_service._build_prompt_description(_MULTI_FIELD_SCHEMA)

    assert "材料名称" in prompt
    assert "规格型号" in prompt
    assert "数量" in prompt


def test_build_prompt_description_includes_descriptions(extraction_service):
    """测试提示描述中包含字段描述。"""
    prompt = extraction_service._build_prompt_description(_MULTI_FIELD_SCHEMA)

    assert "材料的标准名称" in prompt
    assert "规格与型号信息" in prompt
    assert "数量值" in prompt


def test_build_prompt_description_includes_required_label(extraction_service):
    """测试提示描述中包含必填/选填标记。"""
    prompt = extraction_service._build_prompt_description(_MULTI_FIELD_SCHEMA)

    assert "必填" in prompt
    assert "选填" in prompt


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
async def test_extract_batch_multiple_texts(extraction_service, mock_extract):
    """测试批量抽取多段文本。

    通过基于输入文本的 side_effect 函数返回不同结果，
    验证返回列表顺序与输入一致（asyncio.gather 保证结果顺序）。
    """
    texts = [
        "材料为不锈钢",
        "材料为碳钢",
        "材料为铝合金",
    ]

    def _side_effect(text, *args, **kwargs):
        mapping = {
            "材料为不锈钢": {"材料名称": "不锈钢"},
            "材料为碳钢": {"材料名称": "碳钢"},
            "材料为铝合金": {"材料名称": "铝合金"},
        }
        return _make_annotated_document(mapping[text])

    mock_extract.side_effect = _side_effect

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
async def test_extract_batch_partial_failure(extraction_service, mock_extract):
    """测试批量抽取中部分失败时对应位置返回空字典。

    包含 "异常" 的文本触发 langextract.extract 抛出异常，
    应返回空字典而不中断其他抽取。
    """
    texts = ["正常文本", "异常文本", "正常文本2"]

    def _side_effect(text, *args, **kwargs):
        if "异常" in text:
            raise RuntimeError("模型推理失败")
        if text == "正常文本":
            return _make_annotated_document({"材料名称": "不锈钢"})
        return _make_annotated_document({"材料名称": "铝合金"})

    mock_extract.side_effect = _side_effect

    results = await extraction_service.extract_batch(texts, _SIMPLE_SCHEMA)

    assert len(results) == 3
    assert results[0] == {"材料名称": "不锈钢"}
    assert results[1] == {}  # 失败位置返回空字典
    assert results[2] == {"材料名称": "铝合金"}
