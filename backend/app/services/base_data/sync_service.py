"""基础表同步服务（v3 重写，迁移自 project_dict_service）。

从外部接口拉取三表数据 → 全量更新 PostgreSQL → 重建 sm_item Milvus 向量索引。

arq 定时任务每日 2:00 AM 调用 ``sync_all``，也可手动触发。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import numpy as np
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.base_tables import SmFeature, SmItem, SmMethod
from app.services.base_data.loader import BaseTableLoader
from app.services.base_data.store import _make_item_id, base_data_store
from app.services.embedding.embedding_service import embedding_service

logger = get_logger(__name__)


class BaseTableSyncService:
    """基础表同步服务。

    封装三表同步完整流程：外部接口拉取 → PG 全量更新 → Milvus 索引重建。
    通过 ``base_data_store`` 操作 Milvus，通过 ``AsyncSessionLocal`` 操作 PG。
    """

    def __init__(self) -> None:
        self._loader = BaseTableLoader()

    # ------------------------------------------------------------------
    # 步骤 1：拉取外部数据
    # ------------------------------------------------------------------

    async def fetch_from_external_api(self) -> dict[str, list[dict]]:
        """调用外部接口拉取三张基础表全量数据。

        请求 ``PROJECT_DICT_SYNC_URL``，期望返回：
            {"code": 1, "message": "success", "data": [
                {"sm_feature": [...]}, {"sm_item": [...]}, {"sm_method": [...]}
            ]}

        注意：接口 ``code=1`` 表示成功（非 0），需特殊处理。

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
            for tbl_name in tables:
                if tbl_name in item and isinstance(item[tbl_name], list):
                    tables[tbl_name].extend(item[tbl_name])

        logger.info(
            "基础表数据拉取完成",
            feature_count=len(tables["sm_feature"]),
            item_count=len(tables["sm_item"]),
            method_count=len(tables["sm_method"]),
        )
        return tables

    # ------------------------------------------------------------------
    # 步骤 2：全量更新 PostgreSQL
    # ------------------------------------------------------------------

    async def upsert_to_pg(self, tables: dict[str, list[dict]]) -> dict[str, int]:
        """全量更新三张基础表到 PostgreSQL（先全删再批量插入）。

        Args:
            tables: 三表数据字典。

        Returns:
            dict: 各表插入数量统计。
        """
        async with AsyncSessionLocal() as db:
            # 1. 全量删除旧数据
            await db.execute(delete(SmFeature))
            await db.execute(delete(SmItem))
            await db.execute(delete(SmMethod))

            # 2. 批量插入 sm_feature
            feature_count = 0
            for row in tables.get("sm_feature", []):
                db.add(SmFeature(
                    id=int(row.get("ID", 0)),
                    name=str(row.get("NAME", "")).strip(),
                    flag=str(row.get("FLAG", "") or "").strip() or None,
                ))
                feature_count += 1

            # 3. 批量插入 sm_item
            item_count = 0
            for row in tables.get("sm_item", []):
                try:
                    db.add(SmItem(
                        id=int(row.get("id", 0)),
                        name=str(row.get("NAME", "")).strip(),
                        english_name=str(row.get("ENGLISH_NAME", "") or "").strip() or None,
                        item_alias=str(row.get("ITEM_ALIAS", "") or "").strip() or None,
                        unit=str(row.get("UNIT", "") or "").strip() or None,
                        feature=str(row.get("FEATURE", "")).strip(),
                    ))
                    item_count += 1
                except (ValueError, TypeError) as err:
                    logger.warning("sm_item 记录异常跳过", row=row, error=str(err))

            # 4. 批量插入 sm_method
            method_count = 0
            for row in tables.get("sm_method", []):
                try:
                    db.add(SmMethod(
                        id=int(row.get("ID", 0)),
                        type=str(row.get("TYPE", "") or "").strip() or None,
                        name=str(row.get("NAME", "") or "").strip() or None,
                        method_code=str(row.get("METHOD_CODE", "") or "").strip() or None,
                        range=str(row.get("RANGE", "") or "").strip() or None,
                        feature=str(row.get("FEATURE", "") or "").strip() or None,
                    ))
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
        return {"feature": feature_count, "item": item_count, "method": method_count}

    # ------------------------------------------------------------------
    # 步骤 3：重建 Milvus 向量索引
    # ------------------------------------------------------------------

    async def rebuild_vector_index(self, items: list[dict] | None = None) -> int:
        """重新向量化 sm_item 并重建 Milvus base_data 集合。

        向量化策略：
        - 对每个 sm_item，NAME 自身一条向量（alias_idx=0）
        - 每个 ITEM_ALIAS 拆分后的别名各一条向量（alias_idx>0）
        - 同一项目多条向量记录，提升别名召回率

        Args:
            items: 可选，直接传入 sm_item 记录列表；为空则从 PG 加载。

        Returns:
            int: 实际向量化的记录数。
        """
        if items is None:
            items = await self._loader.load_all_items_as_dicts()

        if not items:
            logger.warning("rebuild_vector_index: 无 sm_item 记录，仅清理 Milvus")
            await base_data_store.rebuild([])
            return 0

        # 构造待向量化的文本列表：NAME + 每个别名
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
            await base_data_store.rebuild([])
            return 0

        logger.info("开始向量化 sm_item", extra={"total_texts": len(texts), "items": len(items)})

        # 分批向量化
        batch_size = 64
        all_vectors: list[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            emb = await embedding_service.embed(batch_texts)
            for v in emb["dense_vectors"]:
                all_vectors.append(v)

        # 组装 Milvus 插入数据
        milvus_items: list[dict[str, Any]] = []
        for (item, alias_idx), vec in zip(text_meta, all_vectors):
            milvus_items.append({
                "item_id": _make_item_id(item["feature"], item["name"], alias_idx),
                "canonical_name": item["name"],
                "vector": vec,
                "feature": item["feature"],
                "aliases": item["aliases"],
                "unit": item["unit"],
                "item_pk": item["id"],
            })

        inserted = await base_data_store.rebuild(milvus_items)
        logger.info(
            "基础表向量索引重建完成",
            total_items=len(items),
            total_vectors=len(all_vectors),
            inserted=inserted,
        )
        return inserted

    # ------------------------------------------------------------------
    # 完整同步流程
    # ------------------------------------------------------------------

    async def sync_all(self) -> dict[str, Any]:
        """完整同步流程（arq 定时任务入口）。

        流程：
        1. 调用外部接口拉取三张基础表全量数据
        2. 全量更新 PostgreSQL 三张表
        3. 重新向量化 sm_item + 重建 Milvus base_data 集合

        任一步骤失败则记录日志并返回失败信息，不抛出异常（arq 任务容错）。

        Returns:
            dict: 同步结果统计。
        """
        logger.info("基础表同步开始")

        result: dict[str, Any] = {
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

            # 3. 重建 Milvus 向量索引
            milvus_inserted = await self.rebuild_vector_index()
            result["milvus_inserted"] = milvus_inserted

            logger.info("基础表同步完成", **result)

        except Exception as err:
            logger.error("基础表同步失败", error=str(err), exc_info=True)
            result["status"] = "failed"
            result["error"] = str(err)

        return result


# 模块级单例
base_table_sync_service = BaseTableSyncService()
