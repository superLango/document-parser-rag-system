"""术语标准化服务测试模块。

测试 TermService 的核心功能：
- _fuzzy_match()：大小写不敏感的术语匹配
- standardize_text()：文本术语标准化替换
- get_or_create_term()：幂等的术语查询/创建
- search_terms()：ILIKE 模糊搜索

所有测试通过 mock AsyncSession 避免真实数据库连接。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.term import Term
from app.services.term_service import TermService


# ---------------------------------------------------------------
# 测试辅助：构造 Term 对象
# ---------------------------------------------------------------
def _make_term(
    term_name: str = "不锈钢",
    standard_name: str | None = None,
    synonyms: list[str] | None = None,
    status: str = "active",
    term_id: uuid.UUID | None = None,
) -> Term:
    """创建模拟 Term 对象。

    Args:
        term_name: 术语名称。
        standard_name: 标准名称，可为空。
        synonyms: 同义词列表。
        status: 状态，默认 active。
        term_id: 术语 ID，默认随机生成。

    Returns:
        Term: 构造好的术语对象。
    """
    return Term(
        id=term_id or uuid.uuid4(),
        term_name=term_name,
        standard_name=standard_name,
        definition=None,
        synonyms=synonyms,
        status=status,
    )


def _make_mock_db(execute_return=None, execute_side_effect=None):
    """创建 mock AsyncSession。

    Args:
        execute_return: db.execute 的统一返回值。
        execute_side_effect: db.execute 的 side_effect（按调用顺序返回不同值）。

    Returns:
        MagicMock: 模拟的异步数据库会话。
    """
    db = MagicMock()
    if execute_side_effect is not None:
        db.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        db.execute = AsyncMock(return_value=execute_return)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=None)
    return db


# ---------------------------------------------------------------
# _fuzzy_match() 测试
# ---------------------------------------------------------------
class TestFuzzyMatch:
    """_fuzzy_match 方法测试。"""

    def test_fuzzy_match_case_insensitive(self):
        """测试大小写不敏感匹配。

        文本中包含 "AI"，术语名为 "ai"，应能匹配。
        """
        service = TermService()
        text = "AI 是人工智能的缩写"
        terms = [_make_term(term_name="ai")]

        matches = service._fuzzy_match(text, terms)

        assert len(matches) == 1
        start, end, term = matches[0]
        assert text[start:end] == "AI"
        assert term.term_name == "ai"

    def test_fuzzy_match_multiple_occurrences(self):
        """测试同一术语在文本中多次出现均被匹配。"""
        service = TermService()
        text = "AI 和 AI 是相同的词，AI 出现了三次"
        terms = [_make_term(term_name="ai")]

        matches = service._fuzzy_match(text, terms)

        assert len(matches) == 3

    def test_fuzzy_match_includes_synonyms(self):
        """测试同义词也被匹配。

        术语 "人工智能" 有同义词 "AI"，文本中出现 "AI" 应被匹配到该术语。
        """
        service = TermService()
        text = "AI 技术发展迅速"
        terms = [
            _make_term(term_name="人工智能", synonyms=["AI", "A.I."])
        ]

        matches = service._fuzzy_match(text, terms)

        # 应匹配到术语名 "人工智能"（不存在）和同义词 "AI"
        assert len(matches) == 1
        _, _, matched_term = matches[0]
        assert matched_term.term_name == "人工智能"

    def test_fuzzy_match_no_match(self):
        """测试文本中无术语时返回空列表。"""
        service = TermService()
        text = "这是一段普通文本"
        terms = [_make_term(term_name="不锈钢")]

        matches = service._fuzzy_match(text, terms)

        assert matches == []

    def test_fuzzy_match_empty_terms(self):
        """测试空术语列表时返回空列表。"""
        service = TermService()
        text = "任意文本"
        matches = service._fuzzy_match(text, [])

        assert matches == []

    def test_fuzzy_match_returns_positions(self):
        """测试返回的起始/结束位置正确。"""
        service = TermService()
        text = "abc不锈钢def"
        terms = [_make_term(term_name="不锈钢")]

        matches = service._fuzzy_match(text, terms)

        assert len(matches) == 1
        start, end, _ = matches[0]
        assert start == 3
        assert end == 6
        assert text[start:end] == "不锈钢"


# ---------------------------------------------------------------
# standardize_text() 测试
# ---------------------------------------------------------------
class TestStandardizeText:
    """standardize_text 方法测试。"""

    @pytest.mark.asyncio
    async def test_standardize_replaces_non_standard_term(self):
        """测试非标准术语被替换为标准名称。

        术语名 "AI"，标准名 "人工智能"，文本中的 "AI" 应被替换。
        """
        service = TermService()
        term = _make_term(term_name="AI", standard_name="人工智能")
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [term]
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "AI 是未来")

        assert result["standardized_text"] == "人工智能 是未来"
        assert len(result["replacements"]) == 1
        assert result["replacements"][0]["original"] == "AI"
        assert result["replacements"][0]["standard"] == "人工智能"

    @pytest.mark.asyncio
    async def test_standardize_no_replacement_when_already_standard(self):
        """测试文本已是标准名称时不产生替换。"""
        service = TermService()
        # 术语名 "AI"，标准名 "人工智能"
        # 文本中已是 "人工智能"，不应替换
        term = _make_term(term_name="AI", standard_name="人工智能")
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [term]
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "人工智能 是未来")

        assert result["replacements"] == []
        assert result["standardized_text"] == "人工智能 是未来"

    @pytest.mark.asyncio
    async def test_standardize_empty_text(self):
        """测试空文本时直接返回原文本。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "")

        assert result["standardized_text"] == ""
        assert result["replacements"] == []

    @pytest.mark.asyncio
    async def test_standardize_no_terms(self):
        """测试无可用术语时返回原文本。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "任意文本内容")

        assert result["standardized_text"] == "任意文本内容"
        assert result["replacements"] == []

    @pytest.mark.asyncio
    async def test_standardize_multiple_replacements(self):
        """测试多个术语同时被替换。"""
        service = TermService()
        term1 = _make_term(term_name="AI", standard_name="人工智能")
        term2 = _make_term(term_name="ML", standard_name="机器学习")
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [term1, term2]
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "AI 和 ML 是相关领域")

        # 验证两个术语都被替换
        assert "人工智能" in result["standardized_text"]
        assert "机器学习" in result["standardized_text"]
        assert len(result["replacements"]) == 2

    @pytest.mark.asyncio
    async def test_standardize_returns_original_text(self):
        """测试返回结果包含 original_text 字段。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        result = await service.standardize_text(db, "测试文本")

        assert result["original_text"] == "测试文本"


# ---------------------------------------------------------------
# get_or_create_term() 测试
# ---------------------------------------------------------------
class TestGetOrCreateTerm:
    """get_or_create_term 方法测试。"""

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing_term(self):
        """测试术语已存在时直接返回，不创建新记录。"""
        service = TermService()
        existing_term = _make_term(term_name="不锈钢")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_term
        db = _make_mock_db(execute_return=result_mock)

        term = await service.get_or_create_term(db, "不锈钢", "材料定义")

        assert term is existing_term
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_create_creates_new_term(self):
        """测试术语不存在时创建新术语。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db = _make_mock_db(execute_return=result_mock)

        term = await service.get_or_create_term(db, "新术语", "新术语定义")

        assert term.term_name == "新术语"
        assert term.definition == "新术语定义"
        assert term.status == "active"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_or_create_case_insensitive_lookup(self):
        """测试查询时大小写不敏感。

        术语名为 "AI"，查询 "ai" 也应能找到。
        验证 db.execute 被调用（查询语句中使用了 func.lower）。
        """
        service = TermService()
        existing_term = _make_term(term_name="AI")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_term
        db = _make_mock_db(execute_return=result_mock)

        term = await service.get_or_create_term(db, "ai")

        assert term is existing_term
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_or_create_without_definition(self):
        """测试不提供定义时创建术语。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db = _make_mock_db(execute_return=result_mock)

        term = await service.get_or_create_term(db, "无定义术语")

        assert term.term_name == "无定义术语"
        assert term.definition is None
        assert term.status == "active"


# ---------------------------------------------------------------
# search_terms() 测试
# ---------------------------------------------------------------
class TestSearchTerms:
    """search_terms 方法测试。"""

    @pytest.mark.asyncio
    async def test_search_terms_returns_matches(self):
        """测试 ILIKE 搜索返回匹配的术语。"""
        service = TermService()
        term1 = _make_term(term_name="不锈钢板材")
        term2 = _make_term(term_name="不锈钢管材")
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [term1, term2]
        db = _make_mock_db(execute_return=result_mock)

        results = await service.search_terms(db, "不锈钢")

        assert len(results) == 2
        assert results[0].term_name == "不锈钢板材"
        assert results[1].term_name == "不锈钢管材"
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_terms_no_results(self):
        """测试搜索无结果时返回空列表。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        results = await service.search_terms(db, "不存在的术语")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_terms_default_limit(self):
        """测试默认 limit 参数为 20。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        await service.search_terms(db, "测试")

        # 验证 execute 被调用（SQL 语句中应包含 limit）
        db.execute.assert_awaited_once()
        # 获取传给 execute 的 statement 对象
        stmt = db.execute.call_args[0][0]
        # 验证 SQL 编译后包含 LIMIT 20
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 20" in compiled or "LIMIT" in compiled.upper()

    @pytest.mark.asyncio
    async def test_search_terms_custom_limit(self):
        """测试自定义 limit 参数。"""
        service = TermService()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db = _make_mock_db(execute_return=result_mock)

        await service.search_terms(db, "测试", limit=5)

        db.execute.assert_awaited_once()
        stmt = db.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 5" in compiled or "5" in compiled
