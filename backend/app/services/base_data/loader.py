"""基础表加载器 - 从 PostgreSQL 加载三表数据。

v3 重写（迁移自 project_dict_service），仅负责读取 PG 数据，
不涉及同步和 Milvus 操作。

三表关系（v3 修正）：
- sm_item.FEATURE == sm_feature.NAME  （项目→大类，直接外键）
- sm_method.FEATURE == sm_feature.NAME  （方法→大类，部分错填但不特殊处理，
  直接用 ``sm_method.FEATURE == feature_name`` 查询）
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.base_tables import SmFeature, SmItem, SmMethod

logger = logging.getLogger(__name__)


class BaseTableLoader:
    """基础表加载器，从 PostgreSQL 读取三表数据。

    所有方法均为异步，通过 ``AsyncSessionLocal`` 获取数据库会话。
    返回 ORM 对象列表，调用方可直接访问属性。
    """

    async def load_all_features(self) -> list[SmFeature]:
        """加载 sm_feature 全量记录。

        Returns:
            list[SmFeature]: 项目大类列表，每项含 id/name/flag。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SmFeature).order_by(SmFeature.id))
            rows = result.scalars().all()

        logger.info("加载 sm_feature 完成", extra={"count": len(rows)})
        return list(rows)

    async def load_items_by_feature(self, feature: str) -> list[SmItem]:
        """加载指定 feature 的 sm_item 列表。

        Args:
            feature: 项目大类名（sm_feature.NAME，如 "化学成分"）。

        Returns:
            list[SmItem]: 该大类下的检测项目列表。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SmItem).where(SmItem.feature == feature).order_by(SmItem.id)
            )
            rows = result.scalars().all()

        return list(rows)

    async def load_methods_by_feature(self, feature: str) -> list[SmMethod]:
        """加载指定 feature 的 sm_method 列表。

        v3 修正：sm_method.FEATURE 实际是 feature.name（部分错填），
        直接用 ``sm_method.FEATURE == feature`` 查询即可，不特殊处理错填。

        Args:
            feature: 项目大类名（sm_feature.NAME）。

        Returns:
            list[SmMethod]: 该大类关联的检测方法列表。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SmMethod).where(SmMethod.feature == feature).order_by(SmMethod.id)
            )
            rows = result.scalars().all()

        return list(rows)

    async def load_all_items_as_dicts(self) -> list[dict[str, Any]]:
        """加载全部 sm_item 记录为字典列表（用于 sync 向量化）。

        Returns:
            list[dict]: 每项含 id/name/english_name/aliases/unit/feature。
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SmItem))
            rows = result.scalars().all()

        items: list[dict[str, Any]] = []
        for r in rows:
            aliases: list[str] = []
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
        logger.info("加载全部 sm_item 完成", extra={"count": len(items)})
        return items


# 模块级单例
base_table_loader = BaseTableLoader()
