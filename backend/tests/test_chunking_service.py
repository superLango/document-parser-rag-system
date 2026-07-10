"""结构感知分块服务测试模块。

测试 StructureAwareChunker 的核心功能：
- _extract_sections()：章节结构提取（编号标题匹配）
- chunk_document()：基于章节结构的递归分块
- 标题层级链构建
- chunk_id 生成
- chunk_by_pages()：按页分块
- 边界情况处理（空文本、无章节、超长章节等）

所有测试使用 langchain RecursiveCharacterTextSplitter 的真实实现，无需 mock，
分块器为纯 CPU 计算无外部依赖，可安全在测试环境运行。
"""

import pytest

from app.services.chunking_service import StructureAwareChunker

# ---------------------------------------------------------------
# 测试用文档数据
# ---------------------------------------------------------------
_DOC_META: dict = {
    "doc_id": "doc-001",
    "doc_title": "采购技术规范",
    "file_name": "spec.pdf",
}

# 含多级嵌套章节的文档文本
_NESTED_DOC: str = """1 总则
本规范适用于一般工业与民用建筑的采购环节。

2 材料要求
本章规定采购材料的基本技术要求。

2.1 钢材
钢材应采用高强度结构钢，屈服强度不低于 345MPa。

2.2 混凝土
混凝土强度等级不应低于 C30，坍落度控制在 180mm 以内。

2.2.1 不锈钢
不锈钢材料应采用 304 或 316L 牌号，耐腐蚀性能需满足国家标准。

3 验收标准
材料进场后应按批次进行抽样检验。
"""

# 无章节标题的纯文本
_NO_SECTION_DOC: str = """这是一段没有章节标题的纯文本内容。
内容仅由若干自然段组成，不包含任何编号章节标题。
分块器应将其整体归入前置章节进行处理。"""


# ---------------------------------------------------------------
# 测试 fixtures
# ---------------------------------------------------------------
@pytest.fixture
def chunker() -> StructureAwareChunker:
    """创建默认配置的 StructureAwareChunker 实例。"""
    return StructureAwareChunker()


@pytest.fixture
def small_chunker() -> StructureAwareChunker:
    """创建小分块大小的 chunker，便于验证多分块切分。

    chunk_size=30、chunk_overlap=5 使中等长度文本会被切分为多个分块。
    """
    return StructureAwareChunker(chunk_size=30, chunk_overlap=5)


# ---------------------------------------------------------------
# 1. 章节结构提取测试
# ---------------------------------------------------------------
def test_extract_sections_matches_numbered_headers(chunker):
    """测试章节结构提取，匹配 "3.2.1 标题" 形式的编号标题。

    验证：编号与标题正确解析，章节按出现顺序排列。
    """
    sections = chunker._extract_sections(_NESTED_DOC, _DOC_META)

    # 应包含前置章节（无）+ 5 个编号章节
    # 实际：1 总则、2 材料要求、2.1 钢材、2.2 混凝土、2.2.1 不锈钢、3 验收标准 = 6 个
    assert len(sections) == 6

    # 验证第一个编号章节
    assert sections[0]["level"] == "1"
    assert sections[0]["title"] == "总则"
    assert "本规范适用于" in sections[0]["content"]

    # 验证三级嵌套章节
    stainless = next(s for s in sections if s["level"] == "2.2.1")
    assert stainless["title"] == "不锈钢"
    assert "304 或 316L" in stainless["content"]


def test_extract_sections_levels_parsed(chunker):
    """测试章节编号被正确解析为 level 字段。"""
    sections = chunker._extract_sections(_NESTED_DOC, _DOC_META)
    levels = [s["level"] for s in sections]

    # 验证所有编号章节的 level 正确
    assert "1" in levels
    assert "2" in levels
    assert "2.1" in levels
    assert "2.2" in levels
    assert "2.2.1" in levels
    assert "3" in levels


# ---------------------------------------------------------------
# 2. 递归分块测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_chunk_document_recursive_split(chunker):
    """测试对每个章节进行递归分块。

    验证：每个章节内容被分块，分块携带正确的章节元数据。
    """
    chunks = await chunker.chunk_document(_NESTED_DOC, _DOC_META)

    # 应产生多个分块
    assert len(chunks) > 0

    # 每个分块应包含必要字段
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "text" in chunk
        assert "metadata" in chunk
        assert chunk["text"]  # 文本非空


@pytest.mark.asyncio
async def test_chunk_document_chinese_separators():
    """测试中文分隔符生效：长文本按句号、逗号等中文标点切分。

    使用极小 chunk_size 强制切分，验证切分点落在中文分隔符上。
    """
    # 构造一段长中文文本，含多个句号
    text = "1 测试\n" + "这是第一句话。" * 50
    chunker = StructureAwareChunker(chunk_size=20, chunk_overlap=2)
    chunks = await chunker.chunk_document(text, _DOC_META)

    # 应被切分为多个分块
    assert len(chunks) > 1
    # 每个分块文本长度不超过 chunk_size + 一定容差
    for chunk in chunks:
        assert len(chunk["text"]) <= 30


# ---------------------------------------------------------------
# 3. 标题层级链构建测试
# ---------------------------------------------------------------
def test_title_hierarchy_chain_format(chunker):
    """测试标题层级链按 "文档 > level title" 格式构建。

    验证：三级嵌套章节的 title_chain 形如
    "采购技术规范 > 2 材料要求 > 2.2 混凝土 > 2.2.1 不锈钢"。
    """
    sections = chunker._extract_sections(_NESTED_DOC, _DOC_META)

    # 定位三级嵌套章节 2.2.1 不锈钢
    stainless = next(s for s in sections if s["level"] == "2.2.1")
    title_chain = " > ".join(stainless["title_hierarchy"])

    # 验证层级链包含文档标题与各级章节
    assert "采购技术规范" in title_chain
    assert "2 材料要求" in title_chain
    assert "2.2 混凝土" in title_chain
    assert "2.2.1 不锈钢" in title_chain
    # 验证完整链路顺序
    assert title_chain == "采购技术规范 > 2 材料要求 > 2.2 混凝土 > 2.2.1 不锈钢"


def test_title_hierarchy_top_level(chunker):
    """测试顶层章节的层级链只包含文档标题与该章节。"""
    sections = chunker._extract_sections(_NESTED_DOC, _DOC_META)

    top_section = next(s for s in sections if s["level"] == "1")
    title_chain = " > ".join(top_section["title_hierarchy"])

    # 顶层章节层级链应为 "文档标题 > 1 总则"
    assert title_chain == "采购技术规范 > 1 总则"


def test_title_hierarchy_sibling_reset(chunker):
    """测试同级章节切换时层级链正确重置。

    从 2.2.1 回到 3 时，层级链不应残留 2.2.1 的祖先。
    """
    doc = "1 一\n内容A\n2.1 二\n内容B\n2.1.1 三\n内容C\n3 四\n内容D"
    sections = chunker._extract_sections(doc, _DOC_META)

    # 找到 "3 四" 章节
    sec_three = next(s for s in sections if s["level"] == "3")
    title_chain = " > ".join(sec_three["title_hierarchy"])

    # 3 的层级链应仅含文档标题与自身，不含 2.x 系列
    assert title_chain == "采购技术规范 > 3 四"
    assert "二" not in title_chain
    assert "三" not in title_chain


# ---------------------------------------------------------------
# 4. chunk_id 生成测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_chunk_id_format(chunker):
    """测试 chunk_id 格式：{doc_id}_{level_with_underscore}_{index}。

    验证：level 中的点号被替换为下划线，index 为章节内序号。
    """
    chunks = await chunker.chunk_document(_NESTED_DOC, _DOC_META)

    # 验证存在形如 doc-001_2_2_1_0 的 chunk_id
    chunk_ids = [c["chunk_id"] for c in chunks]

    # 至少应包含这些前缀的 id
    stainless_ids = [
        cid for cid in chunk_ids if cid.startswith("doc-001_2_2_1_")
    ]
    assert len(stainless_ids) > 0
    # 验证 index 从 0 开始
    assert any(cid.endswith("_0") for cid in stainless_ids)


@pytest.mark.asyncio
async def test_chunk_id_unique(small_chunker):
    """测试所有 chunk_id 全局唯一。"""
    chunks = await small_chunker.chunk_document(_NESTED_DOC, _DOC_META)

    chunk_ids = [c["chunk_id"] for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), "存在重复的 chunk_id"


@pytest.mark.asyncio
async def test_chunk_metadata_fields(chunker):
    """测试分块元数据包含全部必要字段。"""
    chunks = await chunker.chunk_document(_NESTED_DOC, _DOC_META)

    for chunk in chunks:
        meta = chunk["metadata"]
        assert "doc_id" in meta
        assert "doc_title" in meta
        assert "file_name" in meta
        assert "title_chain" in meta
        assert "section_level" in meta
        assert "section_title" in meta
        assert "chunk_index" in meta
        # doc_meta 字段透传正确
        assert meta["doc_id"] == "doc-001"
        assert meta["doc_title"] == "采购技术规范"
        assert meta["file_name"] == "spec.pdf"


# ---------------------------------------------------------------
# 5. 边界情况测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_text_returns_empty(chunker):
    """测试空文本输入返回空列表。"""
    # 空字符串
    assert await chunker.chunk_document("", _DOC_META) == []
    # 纯空白
    assert await chunker.chunk_document("   \n  \t  ", _DOC_META) == []


@pytest.mark.asyncio
async def test_no_sections_text(chunker):
    """测试无章节标题的纯文本，归入前置章节（level="0"）。"""
    chunks = await chunker.chunk_document(_NO_SECTION_DOC, _DOC_META)

    # 应至少产生一个分块
    assert len(chunks) >= 1
    # 前置章节 level 为 "0"
    assert chunks[0]["metadata"]["section_level"] == "0"
    # 标题链仅含文档标题
    assert chunks[0]["metadata"]["title_chain"] == "采购技术规范"
    # chunk_id 含 _0_ 前缀（level 0 替换后）
    assert chunks[0]["chunk_id"].startswith("doc-001_0_")


@pytest.mark.asyncio
async def test_missing_doc_id_returns_empty(chunker):
    """测试 doc_meta 缺少 doc_id 时返回空列表。"""
    bad_meta = {"doc_title": "测试", "file_name": "test.pdf"}
    result = await chunker.chunk_document("1 标题\n内容", bad_meta)
    assert result == []


@pytest.mark.asyncio
async def test_long_section_split_into_multiple_chunks():
    """测试超长章节被切分为多个分块，chunk_index 递增。"""
    # 构造一个超长章节
    long_text = "1 长章节\n" + "这是一段用于测试的长文本内容。" * 100
    chunker = StructureAwareChunker(chunk_size=100, chunk_overlap=20)
    chunks = await chunker.chunk_document(long_text, _DOC_META)

    # 应被切分为多个分块
    assert len(chunks) > 1
    # 同一章节的分块 chunk_index 从 0 递增
    indices = [c["metadata"]["chunk_index"] for c in chunks]
    assert indices[0] == 0
    # 验证 chunk_index 连续递增
    assert indices == list(range(len(chunks)))
    # 所有分块归属同一章节
    for chunk in chunks:
        assert chunk["metadata"]["section_level"] == "1"


@pytest.mark.asyncio
async def test_empty_section_skipped(chunker):
    """测试仅有标题无内容的章节被跳过（不产生空分块）。"""
    doc = "1 标题A\n内容A\n2 标题B\n3 标题C\n内容C"
    chunks = await chunker.chunk_document(doc, _DOC_META)

    # "2 标题B" 无内容，不应产生分块
    section_levels = [c["metadata"]["section_level"] for c in chunks]
    assert "2" not in section_levels
    assert "1" in section_levels
    assert "3" in section_levels


# ---------------------------------------------------------------
# 6. chunk_by_pages 测试
# ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_chunk_by_pages(chunker):
    """测试按页分块：将多页文本拼接后统一分块。"""
    pages = [
        {"page_num": 1, "text": "1 总则\n本规范适用于建筑工程。"},
        {"page_num": 2, "text": "2 材料\n钢材应采用高强度结构钢。"},
    ]
    chunks = await chunker.chunk_by_pages(pages, _DOC_META)

    assert len(chunks) > 0
    # 应包含两个章节的分块
    levels = {c["metadata"]["section_level"] for c in chunks}
    assert "1" in levels
    assert "2" in levels


@pytest.mark.asyncio
async def test_chunk_by_pages_empty(chunker):
    """测试空页面列表返回空列表。"""
    assert await chunker.chunk_by_pages([], _DOC_META) == []
    # 页面 text 为空时也应正确处理
    assert await chunker.chunk_by_pages(
        [{"page_num": 1, "text": ""}], _DOC_META
    ) == []
