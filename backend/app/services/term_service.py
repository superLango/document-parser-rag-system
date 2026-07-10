"""术语标准化服务模块。

本模块提供术语库的管理与文本标准化能力，包括：

- 术语的查询与创建（幂等）
- 文本中非标准术语的模糊匹配与替换
- 同义词管理
- 术语搜索（支持名称、标准名、同义词）
- 术语层级树查询
- 术语合并（将源术语合并到目标术语）
- 术语批量导入

所有方法均基于 SQLAlchemy 异步会话操作，使用 flush 推送变更到数据库，
事务的提交由调用方（路由层通过 get_db 依赖）负责。

使用示例：
    from app.services.term_service import term_service

    # 获取或创建术语
    term = await term_service.get_or_create_term(db, "AI", "人工智能")

    # 标准化文本
    result = await term_service.standardize_text(db, "AI 是未来")
    # result["standardized_text"] -> "人工智能 是未来"

    # 添加同义词
    term = await term_service.add_synonym(db, term.id, "A.I.")
"""

from uuid import UUID

from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.term import Term, TermMapping

logger = get_logger(__name__)


class TermService:
    """术语标准化服务。

    封装术语库的全部业务逻辑，包括术语 CRUD、文本标准化、
    同义词管理、术语合并与批量导入等操作。

    所有方法接受外部传入的 AsyncSession，不自行创建或提交事务，
    确保事务边界由调用方统一控制。
    """

    async def get_or_create_term(
        self,
        db: AsyncSession,
        term_name: str,
        definition: str | None = None,
    ) -> Term:
        """查询或创建术语。

        以大小写不敏感方式查询 term_name，若已存在则直接返回，
        否则创建新术语（状态为 active）并返回。

        Args:
            db: 异步数据库会话。
            term_name: 术语名称。
            definition: 术语定义，可为空。

        Returns:
            Term: 已存在或新创建的术语对象。
        """
        # 大小写不敏感查询
        stmt = select(Term).where(func.lower(Term.term_name) == func.lower(term_name))
        result = await db.execute(stmt)
        term = result.scalar_one_or_none()

        if term is not None:
            logger.debug("术语已存在，直接返回", term_id=str(term.id), term_name=term_name)
            return term

        # 创建新术语
        new_term = Term(
            term_name=term_name,
            definition=definition,
            status="active",
        )
        db.add(new_term)
        await db.flush()
        logger.info("创建新术语", term_id=str(new_term.id), term_name=term_name)
        return new_term

    async def standardize_text(
        self,
        db: AsyncSession,
        text: str,
        term_base_id: UUID | None = None,
    ) -> dict:
        """标准化文本中的术语。

        扫描文本中出现的所有已知术语（包括术语名和同义词），
        将非标准表述替换为标准名称，并返回替换记录。

        匹配策略：使用简单的大小写不敏感字符串匹配，优先保留更长的匹配
        以避免短术语覆盖长术语（例如 "A.I." 不会遮蔽 "A.I. System"）。

        Args:
            db: 异步数据库会话。
            text: 待标准化的文本。
            term_base_id: 术语库 ID，预留参数，当前版本未使用，
                未来可用于按术语库分组过滤。

        Returns:
            dict: 标准化结果，包含：
                - original_text: 原始文本
                - standardized_text: 标准化后的文本
                - replacements: 替换记录列表，每条记录包含：
                    - original: 原始文本片段
                    - standard: 标准名称
                    - term_id: 术语 ID
                    - position: [起始位置, 结束位置]
        """
        # 查询所有活跃术语
        stmt = select(Term).where(Term.status == "active")
        result = await db.execute(stmt)
        terms = list(result.scalars().all())

        if not terms or not text:
            logger.debug("无可用术语或空文本，跳过标准化", term_count=len(terms))
            return {
                "original_text": text,
                "standardized_text": text,
                "replacements": [],
            }

        # 模糊匹配：查找所有术语出现位置
        matches = self._fuzzy_match(text, terms)

        if not matches:
            return {
                "original_text": text,
                "standardized_text": text,
                "replacements": [],
            }

        # 按匹配长度降序排序，优先保留更长的匹配以处理重叠
        matches.sort(key=lambda m: (m[1] - m[0], m[0]), reverse=True)

        # 贪心选择不重叠的匹配
        selected: list[tuple[int, int, Term]] = []
        occupied: list[tuple[int, int]] = []
        for start, end, term in matches:
            # 检查是否与已选区间重叠
            has_overlap = any(start < occ_end and end > occ_start for occ_start, occ_end in occupied)
            if not has_overlap:
                selected.append((start, end, term))
                occupied.append((start, end))

        # 按起始位置排序
        selected.sort(key=lambda m: m[0])

        # 构建替换记录列表
        replacements: list[dict] = []
        for start, end, term in selected:
            original = text[start:end]
            # 标准名称：优先使用 standard_name，回退到 term_name
            standard = term.standard_name if term.standard_name else term.term_name
            # 若原始文本已是标准名称，无需替换
            if original.lower() == standard.lower():
                continue
            replacements.append(
                {
                    "original": original,
                    "standard": standard,
                    "term_id": str(term.id),
                    "position": [start, end],
                }
            )

        # 从后往前替换，避免位置偏移
        standardized = text
        for rep in sorted(replacements, key=lambda r: r["position"][0], reverse=True):
            start, end = rep["position"]
            standardized = standardized[:start] + rep["standard"] + standardized[end:]

        logger.info(
            "文本标准化完成",
            original_length=len(text),
            standardized_length=len(standardized),
            replacement_count=len(replacements),
        )

        return {
            "original_text": text,
            "standardized_text": standardized,
            "replacements": replacements,
        }

    async def add_synonym(
        self,
        db: AsyncSession,
        term_id: UUID,
        synonym: str,
    ) -> Term:
        """为术语添加同义词。

        将同义词添加到术语的 synonyms 列表，并创建一条 TermMapping
        记录以持久化该映射关系。

        Args:
            db: 异步数据库会话。
            term_id: 目标术语 ID。
            synonym: 待添加的同义词。

        Returns:
            Term: 更新后的术语对象。

        Raises:
            BusinessException: 术语不存在时抛出。
        """
        term = await db.get(Term, term_id)
        if term is None:
            logger.warning("添加同义词失败：术语不存在", term_id=str(term_id))
            raise BusinessException(
                message=f"术语不存在: {term_id}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            )

        # 更新 synonyms 列表
        synonyms: list[str] = list(term.synonyms or [])
        if synonym not in synonyms:
            synonyms.append(synonym)
            term.synonyms = synonyms
            logger.info("添加同义词", term_id=str(term_id), synonym=synonym)

        # 创建 TermMapping 记录
        mapping = TermMapping(term_id=term_id, original_text=synonym)
        db.add(mapping)
        await db.flush()
        return term

    async def search_terms(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 20,
    ) -> list[Term]:
        """搜索术语。

        对 term_name、standard_name 执行大小写不敏感的 ILIKE 搜索，
        同时在 synonyms JSON 数组中进行文本搜索。

        Args:
            db: 异步数据库会话。
            query: 搜索关键词。
            limit: 返回结果上限，默认 20。

        Returns:
            list[Term]: 匹配的术语列表。
        """
        pattern = f"%{query}%"
        stmt = (
            select(Term)
            .where(
                or_(
                    Term.term_name.ilike(pattern),
                    Term.standard_name.ilike(pattern),
                    cast(Term.synonyms, Text).ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        terms = list(result.scalars().all())
        logger.debug("术语搜索完成", query=query, result_count=len(terms))
        return terms

    async def get_term_tree(self, db: AsyncSession, term_id: UUID) -> dict:
        """获取术语层级树结构。

        查询指定术语及其全部映射记录，返回层级化字典结构。

        Args:
            db: 异步数据库会话。
            term_id: 术语 ID。

        Returns:
            dict: 层级结构，包含：
                - term: 术语详情（id, term_name, standard_name, definition, synonyms, status, created_at）
                - mappings: 映射记录列表，每条含 id, term_id, original_text, created_at

        Raises:
            BusinessException: 术语不存在时抛出。
        """
        stmt = (
            select(Term)
            .options(selectinload(Term.mappings))
            .where(Term.id == term_id)
        )
        result = await db.execute(stmt)
        term = result.scalar_one_or_none()

        if term is None:
            logger.warning("获取术语树失败：术语不存在", term_id=str(term_id))
            raise BusinessException(
                message=f"术语不存在: {term_id}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            )

        return {
            "term": {
                "id": str(term.id),
                "term_name": term.term_name,
                "standard_name": term.standard_name,
                "definition": term.definition,
                "synonyms": term.synonyms or [],
                "status": term.status,
                "created_at": term.created_at.isoformat() if term.created_at else None,
            },
            "mappings": [
                {
                    "id": str(m.id),
                    "term_id": str(m.term_id),
                    "original_text": m.original_text,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in term.mappings
            ],
        }

    async def merge_terms(
        self,
        db: AsyncSession,
        source_id: UUID,
        target_id: UUID,
    ) -> Term:
        """合并术语。

        将源术语合并到目标术语：
        1. 将源术语的名称和同义词合并到目标术语的同义词列表
        2. 将源术语的所有 TermMapping 迁移到目标术语
        3. 删除源术语

        Args:
            db: 异步数据库会话。
            source_id: 源术语 ID（将被删除）。
            target_id: 目标术语 ID（保留并吸收源术语数据）。

        Returns:
            Term: 合并后的目标术语对象。

        Raises:
            BusinessException: 源或目标术语不存在，或两者相同时抛出。
        """
        if source_id == target_id:
            raise BusinessException(
                message="不能将术语合并到自身",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            )

        source = await db.get(Term, source_id)
        target = await db.get(Term, target_id)

        if source is None:
            raise BusinessException(
                message=f"源术语不存在: {source_id}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            )
        if target is None:
            raise BusinessException(
                message=f"目标术语不存在: {target_id}",
                code=ErrorCode.BUSINESS_TASK_FAILED,
            )

        # 合并同义词：目标已有同义词 + 源术语名 + 源术语同义词
        merged_synonyms: set[str] = set(target.synonyms or [])
        merged_synonyms.add(source.term_name)
        if source.synonyms:
            merged_synonyms.update(source.synonyms)
        # 排除目标术语自身的标准名称，避免同义词中出现标准名
        if target.standard_name:
            merged_synonyms.discard(target.standard_name)
        target.synonyms = list(merged_synonyms)

        # 迁移所有 TermMapping 记录到目标术语
        await db.execute(
            update(TermMapping)
            .where(TermMapping.term_id == source_id)
            .values(term_id=target_id)
        )

        # 删除源术语
        await db.execute(delete(Term).where(Term.id == source_id))

        await db.flush()
        logger.info(
            "术语合并完成",
            source_id=str(source_id),
            target_id=str(target_id),
            merged_synonym_count=len(target.synonyms or []),
        )
        return target

    async def import_terms(self, db: AsyncSession, terms: list[dict]) -> int:
        """批量导入术语。

        从字典列表批量导入术语，已存在的术语（名称大小写不敏感匹配）将被跳过。

        每个字典可包含以下键：
            - term_name (必填): 术语名称
            - standard_name (可选): 标准名称
            - definition (可选): 术语定义
            - synonyms (可选): 同义词列表

        Args:
            db: 异步数据库会话。
            terms: 术语字典列表。

        Returns:
            int: 实际导入的术语数量。
        """
        count = 0
        for term_data in terms:
            term_name = term_data.get("term_name")
            if not term_name:
                continue

            # 检查是否已存在（大小写不敏感）
            stmt = select(Term).where(func.lower(Term.term_name) == func.lower(term_name))
            result = await db.execute(stmt)
            if result.scalar_one_or_none() is not None:
                logger.debug("术语已存在，跳过导入", term_name=term_name)
                continue

            new_term = Term(
                term_name=term_name,
                standard_name=term_data.get("standard_name"),
                definition=term_data.get("definition"),
                synonyms=term_data.get("synonyms"),
                status="active",
            )
            db.add(new_term)
            count += 1

        if count > 0:
            await db.flush()
        logger.info("批量导入术语完成", imported_count=count, total_count=len(terms))
        return count

    def _fuzzy_match(
        self,
        text: str,
        terms: list[Term],
    ) -> list[tuple[int, int, Term]]:
        """在文本中查找所有术语出现位置。

        使用简单的大小写不敏感字符串匹配，遍历每个术语的名称和同义词，
        在文本中查找所有出现位置。不做词边界检查，避免引入 NLP 依赖。

        Args:
            text: 待匹配的文本。
            terms: 术语列表。

        Returns:
            list[tuple[int, int, Term]]: 匹配结果列表，每个元素为
                (起始位置, 结束位置, 术语对象)。
        """
        matches: list[tuple[int, int, Term]] = []
        text_lower = text.lower()

        for term in terms:
            # 收集该术语的所有可匹配文本（术语名 + 同义词）
            candidates: list[str] = [term.term_name]
            if term.synonyms:
                candidates.extend(s for s in term.synonyms if s)

            for candidate in candidates:
                candidate_lower = candidate.lower()
                if not candidate_lower:
                    continue
                # 查找所有出现位置
                start = 0
                while True:
                    idx = text_lower.find(candidate_lower, start)
                    if idx == -1:
                        break
                    matches.append((idx, idx + len(candidate_lower), term))
                    start = idx + 1  # 继续查找下一个出现位置

        return matches


# 模块级单例，供整个应用直接导入使用
term_service = TermService()
