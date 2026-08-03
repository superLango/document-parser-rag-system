"""基础表服务（v3 重写，从 project_dict_service 迁移）。

三表同步、加载、sm_item Milvus 索引、项目名归一化匹配。
检索校验逻辑在 services/extraction/phase4_extract/cross_validator.py 中实现。

模块组成：
- models: 三表 ORM 定义（复用 app.models.base_tables）
- sync_service: 三表同步（外部接口 → PG → Milvus）
- loader: 从 PG 加载三表数据
- store: sm_item Milvus 向量索引
- matcher: 项目名归一化匹配
"""

from app.services.base_data.loader import BaseTableLoader, base_table_loader
from app.services.base_data.matcher import ItemMatcher, item_matcher
from app.services.base_data.store import BaseDataStore, base_data_store
from app.services.base_data.sync_service import BaseTableSyncService, base_table_sync_service

__all__ = [
    "BaseTableLoader",
    "base_table_loader",
    "BaseTableSyncService",
    "base_table_sync_service",
    "BaseDataStore",
    "base_data_store",
    "ItemMatcher",
    "item_matcher",
]
