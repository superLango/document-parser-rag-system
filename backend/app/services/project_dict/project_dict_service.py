"""检测项目基础表服务 - 三表同步 + 动态白名单 + 抽取后校验。

对接外部接口 ``PROJECT_DICT_SYNC_URL``（默认 out.dev.lcdp:35002），拉取三张
基础表并分别存储到 PostgreSQL：

- ``sm_feature`` 项目大类（39条）：ID/NAME/FLAG
- ``sm_item`` 检测项目（276条）：id/NAME/ENGLISH_NAME/ITEM_ALIAS/UNIT/FEATURE
  - FEATURE 字段关联 sm_feature.NAME（项目→大类映射，校验跨类混入的核心）
- ``sm_method`` 检测方法（645条）：ID/TYPE/NAME/METHOD_CODE/RANGE/FEATURE
  - FEATURE 为方法分类（如 滴定法、光度法），部分为大类名，作为方法库辅助检索

三表关联：sm_item.FEATURE == sm_feature.NAME，sm_method.FEATURE 部分匹配
sm_feature.NAME（逻辑外键，不强制约束）。

核心能力：
1. **基础表同步**（定时任务触发）：拉取三表 → 全量更新 PG → 重建 Milvus 向量索引
2. **动态白名单生成**（抽取前）：从召回分块提取项目候选 → 向量检索 sm_item
   → 返回标准项目 + 别名 + 大类 → 注入 prompt 约束 LLM 类别边界
3. **抽取后校验**（剔除跨类混入）：LLM 输出项目名 → 向量检索 sm_item top-1
   → top-1.FEATURE != 当前类别 → 标记跨类混入并剔除

向量化策略：
- 对每个 sm_item，将 NAME 和 ITEM_ALIAS 拆分的每个别名都向量化入库
- 同一项目多条向量记录，提升别名召回率（如 Rp0.2 / 规定非比例延伸强度 都能命中）
- 检索时按 FEATURE 过滤，避免跨大类误匹配
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import httpx
import numpy as np
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.base_tables import SmFeature, SmItem, SmMethod
from app.services.project_dict.project_dict_store import (
    _make_item_id,
    project_dict_store,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------
# 项目名候选提取正则
# ---------------------------------------------------------------
# 覆盖标准文档中常见的检测项目命名模式：
# 1. 化学元素符号：C / Si / Mn / P / S / Cr / Ni / Mo / Cu / Ti / Nb / V / W / Co / Al / N / O / H
# 2. 力学性能符号：Rp0.2 / Rm / A / Z / HBW / HRC / HV / HRB / Aku2 / KV2
# 3. 中文项目名：含「强度/伸长率/收缩率/冲击/硬度/吸收功」等关键词
_ELEMENT_PATTERN = re.compile(
    r"\b(?:C|Si|Mn|P|S|Cr|Ni|Mo|Cu|Ti|Nb|V|W|Co|Al|N|O|H|As|Sn|Pb|Bi|Sb|Zr|B|Ca|Mg|Ce|La|Fe)\b"
)
_MECH_SYMBOL_PATTERN = re.compile(
    r"\b(?:Rp\d+\.?\d*|Rm|Rt\d+\.?\d*|A\b|Z\b|Aku\d?|KV\d?|KU\d?|HBW|HRC|HRB|HRA|HV|HS)\b"
)
_CN_PROJECT_PATTERN = re.compile(
    r"[\u4e00-\u9fa5]{2,15}(?:强度|伸长率|收缩率|冲击|硬度|吸收功|韧性|延伸率|屈服|抗拉|"
    r"规定非比例|规定比例|断后|断面|永久|弹性模量|泊松比)"
)


class ProjectDictService:
    """检测项目基础表服务。

    封装三表同步、动态白名单生成、抽取后校验三类能力。
    通过 ``project_dict_store`` 操作 Milvus，通过 ``AsyncSessionLocal``
    操作 PostgreSQL 三张表。
    """

    # ---------------------------------------------------------------
    # 基础表同步：拉取外部接口
    # ---------------------------------------------------------------
    async def fetch_from_external_api(self) -> dict[str, list[dict]]:
        """调用外部接口拉取三张基础表全量数据。

        请求 ``PROJECT_DICT_SYNC_URL``，期望返回：
            {"code": 1, "message": "success", "data": [
                {"sm_feature": [{"ID":1,"NAME":"化学成分","FLAG":"CA"}, ...]},
                {"sm_item":   [{"id":1,"NAME":"C","ENGLISH_NAME":"C","ITEM_ALIAS":"C","UNIT":"%","FEATURE":"化学成分"}, ...]},
                {"sm_method": [{"ID":1,"TYPE":"国家标准","NAME":"...","METHOD_CODE":"GB/T 223.7-2002","RANGE":"...","FEATURE":"滴定法"}, ...]},
            ]}

        注意：接口 ``code=1`` 表示成功（与常规 0 不同），需特殊处理。

        Returns:
            dict: {"sm_feature": [...], "sm_item": [...], "sm_method": [...]}

        Raises:
            RuntimeError: 接口未配置或请求失败。
            ValueError: 接口返回数据格式不符合预期。
        """
        url = settings.PROJECT_DICT_SYNC_URL
        if not url:
            raise RuntimeError("PROJECT_DICT_SYNC_URL 未配置，无法同步基础表")

        headers = {"Accept": "application/json"}
        if settings.PROJECT_DICT_SYNC_API_KEY:
            headers["Authorization"] = f"Bearer {settings.PROJECT_DICT_SYNC_API_KEY}"

        logger.info("开始拉取基础表数据", url=url)

        async with httpx.AsyncClient(timeout=settings.PROJECT_DICT_SYNC_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"基础表接口返回格式异常: {type(payload)}")

        # 接口 code=1 表示成功
        if payload.get("code") not in (0, 1, 200, None):
            raise ValueError(
                f"基础表接口返回业务错误: code={payload.get('code')}, "
                f"message={payload.get('message')}"
            )

        data_list = payload.get("data") or []
        if not isinstance(data_list, list):
            raise ValueError(f"基础表接口 data 字段非数组: {type(data_list)}")

        # data 是数组，每个元素含一个表，合并为三表字典
        tables: dict[str, list[dict]] = {
            "sm_feature": [],
            "sm_item": [],
            "sm_method": [],
        }
        for item in data_list:
            if not isinstance(item, dict):
                continue
            for tbl_name in tables.keys():
                if tbl_name in item:
                    rows = item[tbl_name]
                    if isinstance(rows, list):
                        tables[tbl_name].extend(rows)

        logger.info(
            "基础表数据拉取完成",
            feature_count=len(tables["sm_feature"]),
            item_count=len(tables["sm_item"]),
            method_count=len(tables["sm_method"]),
        )
        return tables

    # ---------------------------------------------------------------
    # 基础表同步：全量更新 PostgreSQL
    # ---------------------------------------------------------------
    async def upsert_to_pg(self, tables: dict[str, list[dict]]) -> dict:
        """全量更新三张基础表到 PostgreSQL。

        采用「先全量删除再批量插入」策略，简单可靠，单事务保证。

        Args:
            tables: 三表数据字典 {"sm_feature":[...], "sm_item":[...], "sm_method":[...]}。

        Returns:
            dict: 各表插入数量统计。
        """
        async with AsyncSessionLocal() as db:
            # 1. 全量删除旧数据（三表）
            await db.execute(delete(SmFeature))
            await db.execute(delete(SmItem))
            await db.execute(delete(SmMethod))

            # 2. 批量插入 sm_feature
            feature_count = 0
            for row in tables.get("sm_feature", []):
                db.add(
                    SmFeature(
                        id=int(row.get("ID", 0)),
                        name=str(row.get("NAME", "")).strip(),
                        flag=str(row.get("FLAG", "") or "").strip() or None,
                    )
                )
                feature_count += 1

            # 3. 批量插入 sm_item
            item_count = 0
            for row in tables.get("sm_item", []):
                try:
                    db.add(
                        SmItem(
                            id=int(row.get("id", 0)),
                            name=str(row.get("NAME", "")).strip(),
                            english_name=str(row.get("ENGLISH_NAME", "") or "").strip() or None,
                            item_alias=str(row.get("ITEM_ALIAS", "") or "").strip() or None,
                            unit=str(row.get("UNIT", "") or "").strip() or None,
                            feature=str(row.get("FEATURE", "")).strip(),
                        )
                    )
                    item_count += 1
                except (ValueError, TypeError) as err:
                    logger.warning("sm_item 记录异常跳过", row=row, error=str(err))

            # 4. 批量插入 sm_method
            method_count = 0
            for row in tables.get("sm_method", []):
                try:
                    db.add(
                        SmMethod(
                            id=int(row.get("ID", 0)),
                            type=str(row.get("TYPE", "") or "").strip() or None,
                            name=str(row.get("NAME", "") or "").strip() or None,
                            method_code=str(row.get("METHOD_CODE", "") or "").strip() or None,
                            range=str(row.get("RANGE", "") or "").strip() or None,
                            feature=str(row.get("FEATURE", "") or "").strip() or None,
                        )
                    )
                    method_count += 1
                except (ValueError, TypeError) as err:
                    logger.warning("sm_method 记录异常跳过", row=row, error=str(err))

            await db.commit()

        logger.info(
            "基础表 PG 全量更新完成",
            feature=feature_count,
            item=item_count,
            method=method_count,
        )
        return {
            "feature": feature_count,
            "item": item_count,
            "method": method_count,
        }

    # ---------------------------------------------------------------
    # 基础表同步：重建 Milvus 向量索引
    # ---------------------------------------------------------------
    async def _load_items_from_pg(self) -> list[dict]:
        """从 PostgreSQL 加载全部 sm_item 记录。

        Returns:
            list[dict]: sm_item 记录列表，每项包含
                id/name/english_name/item_alias/unit/feature。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SmItem))
            rows = result.scalars().all()

        items = []
        for r in rows:
            # 拆分别名：item_alias 可能是逗号分隔或单个别名
            aliases = []
            if r.item_alias:
                aliases = [s.strip() for s in r.item_alias.split(",") if s.strip()]
            items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "english_name": r.english_name or "",
                    "aliases": aliases,
                    "unit": r.unit or "",
                    "feature": r.feature,
                }
            )
        return items

    async def rebuild_vector_index(self, items: list[dict] | None = None) -> int:
        """重新向量化 sm_item 并重建 Milvus project_dict 集合。

        向量化策略：
        - 对每个 sm_item，NAME 自身一条向量（alias_idx=0）
        - 每个 ITEM_ALIAS 拆分后的别名各一条向量（alias_idx>0）
        - 同一项目多条向量记录，提升别名召回率

        Args:
            items: 可选，直接传入 sm_item 记录列表；为空则从 PG 加载。

        Returns:
            int: 实际向量化的记录数（含 NAME + 别名的总向量数）。
        """
        from app.services.embedding.embedding_service import embedding_service

        if items is None:
            items = await self._load_items_from_pg()

        if not items:
            logger.warning("rebuild_vector_index: 无 sm_item 记录，仅清理 Milvus")
            await project_dict_store.rebuild([])
            return 0

        # 构造待向量化的文本列表：NAME + 每个别名
        # 同时记录每个文本对应的 (item, alias_idx)
        texts: list[str] = []
        text_meta: list[tuple[dict, int]] = []  # (item, alias_idx)

        for item in items:
            if not item["name"] or not item["feature"]:
                continue
            # NAME 自身
            texts.append(item["name"])
            text_meta.append((item, 0))
            # 每个别名
            for idx, alias in enumerate(item["aliases"], start=1):
                if alias and alias != item["name"]:
                    texts.append(alias)
                    text_meta.append((item, idx))

        if not texts:
            logger.warning("rebuild_vector_index: 无可向量化的项目名")
            await project_dict_store.rebuild([])
            return 0

        logger.info("开始向量化 sm_item", total_texts=len(texts), items=len(items))

        # 分批向量化
        batch_size = 64
        all_vectors: list[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            emb = await embedding_service.embed(batch_texts)
            for v in emb["dense_vectors"]:
                all_vectors.append(v)

        # 组装 Milvus 插入数据
        milvus_items = []
        for (item, alias_idx), text, vec in zip(text_meta, texts, all_vectors):
            milvus_items.append(
                {
                    "item_id": _make_item_id(item["feature"], item["name"], alias_idx),
                    "canonical_name": item["name"],
                    "vector": vec,
                    "feature": item["feature"],
                    "aliases": item["aliases"],
                    "unit": item["unit"],
                    "item_pk": item["id"],
                }
            )

        inserted = await project_dict_store.rebuild(milvus_items)
        logger.info(
            "基础表向量索引重建完成",
            total_items=len(items),
            total_vectors=len(all_vectors),
            inserted=inserted,
        )
        return inserted

    async def sync_all(self) -> dict:
        """完整同步流程（arq 定时任务入口）。

        流程：
        1. 调用外部接口拉取三张基础表全量数据
        2. 全量更新 PostgreSQL 三张表
        3. 重新向量化 sm_item + 重建 Milvus project_dict 集合

        任一步骤失败则记录日志并返回失败信息，不抛出异常（arq 任务容错）。

        Returns:
            dict: 同步结果统计。
        """
        logger.info("基础表同步开始")

        result = {
            "fetched": {"feature": 0, "item": 0, "method": 0},
            "pg_inserted": {"feature": 0, "item": 0, "method": 0},
            "milvus_inserted": 0,
            "status": "success",
            "error": None,
        }

        try:
            # 1. 拉取外部数据
            tables = await self.fetch_from_external_api()
            result["fetched"] = {
                "feature": len(tables["sm_feature"]),
                "item": len(tables["sm_item"]),
                "method": len(tables["sm_method"]),
            }

            # 2. 全量更新 PG
            pg_result = await self.upsert_to_pg(tables)
            result["pg_inserted"] = pg_result

            # 3. 重建 Milvus 向量索引（基于 sm_item）
            milvus_inserted = await self.rebuild_vector_index()
            result["milvus_inserted"] = milvus_inserted

            logger.info("基础表同步完成", **result)

        except Exception as err:
            logger.error("基础表同步失败", error=str(err), exc_info=True)
            result["status"] = "failed"
            result["error"] = str(err)

        return result

    # ---------------------------------------------------------------
    # 文档驱动抽取：识别文档涉及的大类
    # ---------------------------------------------------------------
    async def detect_document_categories(
        self,
        doc_id: str,
        top_k_per_candidate: int = 3,
        min_hit_score: float | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """根据文档内容识别涉及的项目大类（sm_feature.NAME）。

        文档驱动抽取的核心：先用文档内容反向匹配基础表，识别出文档实际
        涉及哪些大类，再据此生成抽取 categories，避免「schema 写了但文档没有」
        或「文档有但 schema 没写」的覆盖偏差。

        流程：
        1. 从 Milvus ``doc_chunks`` 集合拉取该文档全部分块文本
        2. 用三类正则从分块文本提取项目候选
           （化学元素 / 力学符号 / 中文项目名）
        3. 候选向量化（bge-m3）→ 全库检索 ``sm_item`` top-K（不限大类）
        4. 按 ``sm_item.feature`` 聚合统计命中次数
        5. 返回命中次数 > 0 的大类列表（按命中次数降序）

        Args:
            doc_id: 文档 ID。
            top_k_per_candidate: 每个候选项检索返回的 top-K（默认 3）。
            min_hit_score: 命中阈值，``None`` 时使用配置 ``PROJECT_DICT_MATCH_THRESHOLD``。

        Returns:
            list[dict]: 文档涉及的大类列表，每项包含：
                - feature: sm_feature.NAME（大类名）
                - hit_count: 命中次数（候选匹配到该大类下的项目总数）
                - matched_items: 命中的标准项目名示例（前 5 个）
                - flag: sm_feature.FLAG（大类代码）
        """
        if min_hit_score is None:
            min_hit_score = settings.PROJECT_DICT_MATCH_THRESHOLD

        # 1. 拉取文档全部分块文本
        from app.services.vector.chunk_vector_store import vector_store

        vector_store._ensure_connected()
        from pymilvus import Collection

        collection = Collection(settings.MILVUS_COLLECTION)
        collection.load()
        query_result = collection.query(
            expr=f'doc_id == "{doc_id}"',
            output_fields=["text"],
            limit=200,
        )
        chunks = [r.get("text", "") for r in query_result if r.get("text")]
        if not chunks:
            logger.warning("文档大类识别：未找到文档分块", doc_id=doc_id)
            return []

        full_text = "\n\n".join(chunks)
        logger.info(
            "文档大类识别：已加载文档分块",
            doc_id=doc_id,
            chunk_count=len(chunks),
            text_len=len(full_text),
        )

        # 2. 提取项目候选
        candidates = self.extract_project_candidates(full_text)
        if not candidates:
            logger.warning("文档大类识别：未提取到项目候选", doc_id=doc_id)
            return []

        # 去重（保持顺序）
        seen: set[str] = set()
        unique_candidates: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)
        candidates = unique_candidates

        logger.info(
            "文档大类识别：候选项目数",
            doc_id=doc_id,
            candidate_count=len(candidates),
            sample=candidates[:10],
        )

        # 3. 候选向量化
        from app.services.embedding.embedding_service import embedding_service

        try:
            emb = await embedding_service.embed(candidates)
        except Exception as err:
            logger.error("文档大类识别：候选向量化失败", error=str(err))
            return []

        # 4. 全库检索 sm_item top-K（方案 6：批量并发检索）
        feature_hits: dict[str, dict] = {}  # feature -> {hit_count, matched_items:set}

        async def _search_one_candidate(vec: np.ndarray) -> list[dict]:
            try:
                return await project_dict_store.search(
                    query_vector=vec,
                    top_k=top_k_per_candidate,
                    kb_id=kb_id,
                )
            except Exception as err:
                logger.warning("文档大类识别：检索失败", error=str(err))
                return []

        # 并发检索所有候选（asyncio.gather + asyncio.to_thread 真并发）
        all_hits = await asyncio.gather(
            *[_search_one_candidate(v) for v in emb["dense_vectors"]]
        )

        for hits in all_hits:
            for hit in hits:
                if hit["score"] < min_hit_score:
                    continue
                feature = hit["feature"]
                if not feature:
                    continue
                if feature not in feature_hits:
                    feature_hits[feature] = {
                        "hit_count": 0,
                        "matched_items": set(),
                    }
                feature_hits[feature]["hit_count"] += 1
                feature_hits[feature]["matched_items"].add(hit["canonical_name"])

        # 5. 加载 sm_feature.FLAG 用于返回
        feature_flag_map: dict[str, str | None] = {}
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(SmFeature.name, SmFeature.flag))
                for name, flag in result.fetchall():
                    feature_flag_map[name] = flag
        except Exception as err:
            logger.warning("文档大类识别：加载 sm_feature 失败", error=str(err))

        # 6. 按命中次数降序输出（方案 11：增加命中次数阈值过滤噪声大类）
        min_hits = settings.PROJECT_DICT_DOC_DETECT_MIN_HITS
        sorted_features = sorted(
            feature_hits.items(),
            key=lambda x: x[1]["hit_count"],
            reverse=True,
        )

        detected: list[dict] = []
        skipped_low_hits: list[dict] = []
        for feature, info in sorted_features:
            if info["hit_count"] < min_hits:
                # 命中次数低于阈值视为噪声，不纳入文档涉及大类
                logger.debug(
                    "文档大类识别：命中次数不足阈值，跳过",
                    feature=feature,
                    hit_count=info["hit_count"],
                    min_hits=min_hits,
                )
                skipped_low_hits.append(
                    {"feature": feature, "hit_count": info["hit_count"]}
                )
                continue
            detected.append(
                {
                    "feature": feature,
                    "hit_count": info["hit_count"],
                    "matched_items": list(info["matched_items"])[:5],
                    "flag": feature_flag_map.get(feature),
                }
            )

        logger.info(
            "文档大类识别完成",
            doc_id=doc_id,
            detected_count=len(detected),
            features=[d["feature"] for d in detected],
            skipped_low_hits=len(skipped_low_hits),
            min_hits_threshold=min_hits,
        )
        return detected

    # ---------------------------------------------------------------
    # 动态白名单生成
    # ---------------------------------------------------------------
    def extract_project_candidates(self, text: str) -> list[str]:
        """从召回分块文本中提取项目名候选。

        使用三类正则模式提取：
        1. 化学元素符号（C/Si/Mn/Cr/Ni 等）
        2. 力学性能符号（Rp0.2/Rm/A/Z/HBW 等）
        3. 中文项目名（含「强度/伸长率/冲击/硬度」等关键词）

        去重后返回，保持出现顺序。

        Args:
            text: 召回分块拼接文本。

        Returns:
            list[str]: 项目名候选列表（去重）。
        """
        if not text:
            return []

        candidates: list[str] = []
        seen: set[str] = set()

        for pattern in (_ELEMENT_PATTERN, _MECH_SYMBOL_PATTERN, _CN_PROJECT_PATTERN):
            for m in pattern.finditer(text):
                cand = m.group().strip()
                if cand and cand not in seen:
                    seen.add(cand)
                    candidates.append(cand)

        return candidates

    async def build_dynamic_whitelist(
        self,
        category: str,
        recalled_chunks: list[str],
        top_k: int | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """为指定大类生成动态 prompt 白名单。

        流程：
        1. 从召回分块提取项目名候选（正则）
        2. 候选向量化（bge-m3）
        3. Milvus 大类内检索 top-K（``expr: feature == "X"``）
        4. 合并去重，返回标准项目 + 别名 + 单位

        若候选提取为空，则用召回分块前 N 字符作为 query 兜底检索。

        Args:
            category: 当前抽取的项目大类（对应 sm_item.FEATURE）。
            recalled_chunks: 向量检索召回的分块文本列表。
            top_k: 白名单返回的项目数，默认取配置 ``PROJECT_DICT_WHITELIST_TOP_K``。

        Returns:
            list[dict]: 白名单项目列表，每项包含：
                - canonical: 标准项目名
                - aliases: 别名列表（取前 3 个示例）
                - unit: 标准单位
                - score: 匹配置信度
        """
        if top_k is None:
            top_k = settings.PROJECT_DICT_WHITELIST_TOP_K

        # 1. 提取候选
        combined_text = "\n".join(recalled_chunks)
        candidates = self.extract_project_candidates(combined_text)

        # 候选为空时，用召回文本片段兜底
        if not candidates:
            candidates = [c[:100] for c in recalled_chunks if c][:5]

        if not candidates:
            logger.warning("动态白名单生成：无候选项目", category=category)
            return []

        # 2. 候选向量化
        from app.services.embedding.embedding_service import embedding_service

        try:
            emb = await embedding_service.embed(candidates)
        except Exception as err:
            logger.error("动态白名单：候选向量化失败", category=category, error=str(err))
            return []

        # 3. 大类内检索 + 去重（方案 6：批量并发检索）
        whitelist: list[dict] = []
        seen_canonical: set[str] = set()

        async def _search_one_in_feature(vec: np.ndarray) -> list[dict]:
            try:
                return await project_dict_store.search_by_feature(
                    query_vector=vec,
                    feature=category,
                    top_k=min(3, top_k),
                    kb_id=kb_id,
                )
            except Exception as err:
                logger.warning(
                    "动态白名单：大类内检索失败",
                    category=category,
                    error=str(err),
                )
                return []

        # 并发检索所有候选（asyncio.gather + asyncio.to_thread 真并发）
        all_hits = await asyncio.gather(
            *[_search_one_in_feature(v) for v in emb["dense_vectors"]]
        )

        for hits in all_hits:
            for hit in hits:
                if hit["score"] < settings.PROJECT_DICT_MATCH_THRESHOLD:
                    continue
                canonical = hit["canonical_name"]
                if canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)
                whitelist.append(
                    {
                        "canonical": canonical,
                        "aliases": hit["aliases"][:3],
                        "unit": hit["unit"],
                        "score": hit["score"],
                    }
                )
                if len(whitelist) >= top_k:
                    break
            if len(whitelist) >= top_k:
                break

        logger.info(
            "动态白名单生成完成",
            category=category,
            candidates=len(candidates),
            whitelist_size=len(whitelist),
        )
        return whitelist

    # 旧接口名保留别名，向后兼容
    build_dynamic_whitelist_by_category = build_dynamic_whitelist

    # ---------------------------------------------------------------
    # 抽取后校验
    # ---------------------------------------------------------------
    async def _load_feature_names(
        self, kb_id: uuid.UUID | None = None
    ) -> set[str]:
        """从 PG 加载 sm_feature.NAME 集合（用于判断 category 是否在基础表中）。

        知识库隔离：sm_feature 为基础三表，遵循"全局共享 + KB 覆盖"。
        ``kb_id`` 非 None 时返回全局（kb_id IS NULL）+ 该 KB 覆盖的 feature；
        ``kb_id`` 为 None 时返回全部（向后兼容）。

        Args:
            kb_id: 知识库 ID，None 表示返回全部。

        Returns:
            set[str]: sm_feature.NAME 集合。
        """
        async with AsyncSessionLocal() as db:
            if kb_id is None:
                result = await db.execute(select(SmFeature.name))
            else:
                from sqlalchemy import or_
                result = await db.execute(
                    select(SmFeature.name).where(
                        or_(SmFeature.kb_id.is_(None), SmFeature.kb_id == kb_id)
                    )
                )
            return {r[0] for r in result.fetchall() if r[0]}

    @staticmethod
    def _is_category_match(top_feature: str, category: str) -> bool:
        """判断 top-1 检索到的大类是否与当前抽取类别匹配。

        匹配规则（按优先级）：
        1. 完全相等：top_feature == category
        2. 子类匹配：top_feature 包含 category（如「布氏硬度」包含「硬度」）
        3. 子类匹配：category 包含 top_feature（如「硬度」包含「布氏硬度」?否，
           实际是 top_feature 是细分，「硬度」是粗类，所以用规则2）

        示例：
        - category=硬度, top_feature=布氏硬度 → 「布氏硬度」包含「硬度」 ✓
        - category=冲击, top_feature=夏比冲击 → 「夏比冲击」包含「冲击」 ✓
        - category=室温拉伸, top_feature=布氏硬度 → 不包含 ✗
        - category=化学成分, top_feature=化学成分 → 完全相等 ✓

        Args:
            top_feature: 检索到的 sm_item.FEATURE 值。
            category: 当前抽取的类别名。

        Returns:
            bool: 是否匹配。
        """
        if top_feature == category:
            return True
        # 子类匹配：top_feature 是 category 的细分（如 布氏硬度 ⊂ 硬度）
        if category in top_feature:
            return True
        # 反向子类匹配：category 是 top_feature 的细分（少见，保留兼容）
        if top_feature in category:
            return True
        return False

    async def validate_records(
        self,
        records: list[dict],
        category: str,
        kb_id: uuid.UUID | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """校验抽取记录的大类归属，剔除跨类混入。

        对每条记录的「项目」字段向量化，检索 sm_item top-1：
        - top-1.feature 与 category 匹配（含子类匹配）→ 保留
        - top-1.feature 不匹配 → 标记跨类混入，剔除
        - score < 阈值 → 标记未匹配，保留但加 warning（可能基础表未覆盖）

        特殊处理：如果 category 不在 sm_feature.NAME 中（如「气体分析」
        基础表无此大类），跳过校验，保留所有记录（标记 _match_status=skipped）。

        Args:
            records: LLM 抽取的记录列表（每条含「项目」字段）。
            category: 当前抽取的大类。

        Returns:
            tuple[list[dict], list[dict]]: (合法记录, 被剔除记录)，
            被剔除记录附加 _reject_reason 字段。
        """
        if not records:
            return [], []

        # 检查 category 是否在 sm_feature.NAME 中
        # 不在则跳过校验（如「气体分析」基础表无此大类）
        try:
            feature_names = await self._load_feature_names(kb_id=kb_id)
        except Exception as err:
            logger.warning("校验：加载 sm_feature 失败，跳过校验", error=str(err))
            return records, []

        if category not in feature_names:
            logger.info(
                "校验跳过：category 不在 sm_feature 中",
                category=category,
                reason="基础表无此大类，可能为复合类别（如气体分析）",
            )
            return [
                {**r, "_match_status": "skipped"} for r in records
            ], []

        # 收集所有待校验的项目名
        project_names = [str(r.get("项目", "")).strip() for r in records]
        project_names = [p for p in project_names if p]

        if not project_names:
            return records, []

        from app.services.embedding.embedding_service import embedding_service

        # 批量向量化项目名
        try:
            emb = await embedding_service.embed(project_names)
        except Exception as err:
            logger.error("校验：项目名向量化失败", category=category, error=str(err))
            return records, []

        # 逐条检索 top-1 校验（方案 6：批量并发检索）
        valid: list[dict] = []
        rejected: list[dict] = []

        async def _search_one_record(vec: np.ndarray) -> list[dict]:
            try:
                return await project_dict_store.search(vec, top_k=1, kb_id=kb_id)
            except Exception as err:
                logger.warning("校验：向量检索失败", error=str(err))
                return []

        # 并发检索所有记录（asyncio.gather + asyncio.to_thread 真并发）
        # 校验阶段通常 1000+ 条记录，并发后耗时从 5-10 分钟降至秒级
        all_hits = await asyncio.gather(
            *[_search_one_record(v) for v in emb["dense_vectors"]]
        )

        for record, project_name, hits in zip(records, project_names, all_hits):
            if not hits:
                valid.append(record)
                continue

            top_hit = hits[0]
            top_feature = top_hit["feature"]
            top_score = top_hit["score"]

            if top_score < settings.PROJECT_DICT_MATCH_THRESHOLD:
                # 低置信度：基础表可能未覆盖，保留但标记
                record = {**record, "_match_score": top_score, "_match_status": "low_confidence"}
                valid.append(record)
                continue

            if self._is_category_match(top_feature, category):
                record = {**record, "_match_score": top_score, "_match_status": "matched"}
                valid.append(record)
            else:
                # 跨类混入，剔除
                rejected_record = {
                    **record,
                    "_reject_reason": f"项目「{project_name}」属 {top_feature}，非 {category}",
                    "_match_category": top_feature,
                    "_match_score": top_score,
                }
                rejected.append(rejected_record)

        logger.info(
            "抽取后校验完成",
            category=category,
            total=len(records),
            valid=len(valid),
            rejected=len(rejected),
        )
        return valid, rejected

    # ---------------------------------------------------------------
    # prompt 白名单渲染
    # ---------------------------------------------------------------
    @staticmethod
    def render_whitelist_prompt(
        category: str,
        whitelist: list[dict],
    ) -> str:
        """将动态白名单渲染为 prompt 片段。

        输出紧凑的白名单文本（~1K token），包含：
        - 当前大类说明
        - 标准项目列表（canonical + 别名示例）
        - 禁止抽取的负样本提示

        Args:
            category: 当前抽取大类。
            whitelist: ``build_dynamic_whitelist`` 返回的白名单列表。

        Returns:
            str: 可直接拼接到 prompt_description 的文本片段。
        """
        if not whitelist:
            return ""

        items = []
        for i, w in enumerate(whitelist, 1):
            alias_str = "、".join(w["aliases"]) if w["aliases"] else "无"
            items.append(f"{i}. {w['canonical']}（别名示例：{alias_str}）")

        items_text = "\n".join(items)

        return (
            f"\n\n【{category} 类别项目白名单】\n"
            f"当前仅抽取以下标准项目及其语义变体（按语义匹配，非字面匹配）：\n"
            f"{items_text}\n\n"
            f"【严格约束】\n"
            f"- 仅抽取上述白名单内的项目，禁止抽取其他大类的项目\n"
            f"- 项目名可能存在变体（上下标/LaTeX 残留/简写），按语义判断归属\n"
            f"- 无法归入白名单的项目，跳过该行，不要硬塞\n"
            f"- 保留原始符号（≥/≤/~），不要丢失"
        )


# 模块级单例
project_dict_service = ProjectDictService()
