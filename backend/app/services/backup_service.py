"""知识库数据备份与恢复服务（阶段 3 - 数据备份恢复）。

将 KB 的配置、文档元数据、抽取结果、术语、Schema、领域配置打包为 ZIP，
存储到 KB 专属 MinIO bucket 的 ``backups/`` 前缀下；支持从 ZIP 恢复。

备份内容（ZIP 结构）：
    manifest.json        备份清单（KB 信息 + 各资源条数 + 时间戳）
    config.json          KB 配置 JSON
    documents.json       文档元数据列表（含 structured_data 抽取结果）
    schemas.json         Schema 配置列表
    terms.json           术语与术语映射列表
    domain_config.json   领域配置（类别/正则/字段模板/字典配置）

恢复策略：
    - 文档：按 filename 去重，已存在的跳过（避免覆盖原文件）
    - Schema：按 name 去重，已存在的跳过
    - 术语：按 term_name 去重，已存在的跳过
    - 配置：直接覆盖 KB config JSON
    - 领域配置：先清理再写入（幂等）
"""

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.backup import KbBackup
from app.models.document import Document
from app.models.kb_domain_config import (
    KbCategory,
    KbDictConfig,
    KbFieldTemplate,
    KbRegexRule,
)
from app.models.knowledge_base import KnowledgeBase
from app.models.schema_model import SchemaConfig
from app.models.term import Term, TermMapping
from app.services.storage_service import storage_service

logger = get_logger(__name__)

# 备份在 MinIO bucket 内的对象前缀
_BACKUP_PREFIX = "backups/"


def _datetime_str(dt: datetime | None) -> str:
    """安全序列化 datetime 为 ISO 字符串。"""
    return dt.isoformat() if dt else ""


async def create_backup(
    db: AsyncSession,
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
) -> KbBackup:
    """创建 KB 数据备份，打包为 ZIP 并上传到 KB 专属 bucket。

    Args:
        db: 异步数据库会话（已激活 RLS，查询自动按 kb_id 过滤）。
        kb_id: 知识库 ID。
        user_id: 发起备份的用户 ID。

    Returns:
        KbBackup: 备份记录。
    """
    logger.info("开始创建 KB 备份", kb_id=str(kb_id), user_id=str(user_id))

    # 1. 收集各资源数据（所有查询显式按 kb_id 过滤，纵深防御不依赖 RLS，
    #    因 PostgreSQL superuser 绕过 RLS）
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    ).scalar_one_or_none()
    kb_info = {
        "id": str(kb.id) if kb else "",
        "name": kb.name if kb else "",
        "template_code": kb.template_code if kb else "",
        "config": kb.config if (kb and isinstance(kb.config, dict)) else {},
    }

    documents = (
        await db.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at)
        )
    ).scalars().all()
    docs_data = [
        {
            "id": str(d.id),
            "filename": d.filename,
            "file_size": d.file_size,
            "file_type": d.file_type,
            "status": d.status,
            "parsed_text": d.parsed_text or "",
            "structured_data": d.structured_data,
            "layout_data": d.layout_data,
            "created_at": _datetime_str(d.created_at),
            "updated_at": _datetime_str(d.updated_at),
        }
        for d in documents
    ]

    schemas = (
        await db.execute(
            select(SchemaConfig)
            .where(SchemaConfig.kb_id == kb_id)
            .order_by(SchemaConfig.created_at)
        )
    ).scalars().all()
    schemas_data = [
        {
            "id": str(s.id),
            "name": s.name,
            "description": s.description or "",
            "parent_id": str(s.parent_id) if s.parent_id else None,
            "schema_definition": s.schema_definition,
            "sample_fields": s.sample_fields,
            "is_active": s.is_active,
            "sort_order": s.sort_order,
            "is_template": s.is_template,
            "created_at": _datetime_str(s.created_at),
        }
        for s in schemas
    ]

    terms = (
        await db.execute(
            select(Term).where(Term.kb_id == kb_id).order_by(Term.created_at)
        )
    ).scalars().all()
    terms_data = [
        {
            "id": str(t.id),
            "term_name": t.term_name,
            "standard_name": t.standard_name,
            "definition": t.definition or "",
            "synonyms": t.synonyms,
            "status": t.status,
            "category": t.category,
            "standard_number": t.standard_number,
            "created_at": _datetime_str(t.created_at),
        }
        for t in terms
    ]

    term_mappings = (
        await db.execute(
            select(TermMapping).where(TermMapping.kb_id == kb_id)
        )
    ).scalars().all()
    mappings_data = [
        {
            "id": str(tm.id),
            "term_id": str(tm.term_id),
            "original_text": tm.original_text,
            "created_at": _datetime_str(tm.created_at),
        }
        for tm in term_mappings
    ]

    # 领域配置
    categories = (
        await db.execute(
            select(KbCategory)
            .where(KbCategory.kb_id == kb_id)
            .order_by(KbCategory.sort_order)
        )
    ).scalars().all()
    categories_data = [
        {
            "id": str(c.id),
            "name": c.name,
            "extraction_class": c.extraction_class,
            "description": c.description or "",
            "is_active": c.is_active,
            "sort_order": c.sort_order,
            "recall_filter_threshold": c.recall_filter_threshold,
        }
        for c in categories
    ]

    regex_rules = (
        await db.execute(
            select(KbRegexRule)
            .where(KbRegexRule.kb_id == kb_id)
            .order_by(KbRegexRule.sort_order)
        )
    ).scalars().all()
    regex_data = [
        {
            "id": str(r.id),
            "name": r.name,
            "pattern": r.pattern,
            "description": r.description or "",
            "enabled": r.enabled,
            "sort_order": r.sort_order,
        }
        for r in regex_rules
    ]

    field_templates = (
        await db.execute(
            select(KbFieldTemplate).where(KbFieldTemplate.kb_id == kb_id)
        )
    ).scalars().all()
    fields_data = [
        {
            "id": str(f.id),
            "template_type": f.template_type,
            "fields": f.fields,
            "prompt": f.prompt,
        }
        for f in field_templates
    ]

    dict_configs = (
        await db.execute(
            select(KbDictConfig).where(KbDictConfig.kb_id == kb_id)
        )
    ).scalars().all()
    dict_data = [
        {
            "id": str(dc.id),
            "enabled": dc.enabled,
            "sync_url": dc.sync_url,
            "sync_api_key": dc.sync_api_key,
            "sync_cron": dc.sync_cron,
            "match_threshold": dc.match_threshold,
            "whitelist_top_k": dc.whitelist_top_k,
            "validation_top_k": dc.validation_top_k,
            "validation_similarity_threshold": dc.validation_similarity_threshold,
            "tables_mapping": dc.tables_mapping,
        }
        for dc in dict_configs
    ]

    domain_config = {
        "categories": categories_data,
        "regex_rules": regex_data,
        "field_templates": fields_data,
        "dict_configs": dict_data,
    }

    # 2. 构造 manifest
    item_counts = {
        "documents": len(docs_data),
        "schemas": len(schemas_data),
        "terms": len(terms_data),
        "term_mappings": len(mappings_data),
        "categories": len(categories_data),
        "regex_rules": len(regex_data),
        "field_templates": len(fields_data),
        "dict_configs": len(dict_data),
    }
    manifest = {
        "backup_version": "1.0",
        "kb_id": str(kb_id),
        "kb_name": kb_info["name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": str(user_id),
        "item_counts": item_counts,
    }

    # 3. 打包 ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("config.json", json.dumps(kb_info, ensure_ascii=False, indent=2))
        zf.writestr("documents.json", json.dumps(docs_data, ensure_ascii=False, indent=2))
        zf.writestr("schemas.json", json.dumps(schemas_data, ensure_ascii=False, indent=2))
        zf.writestr(
            "terms.json",
            json.dumps(
                {"terms": terms_data, "mappings": mappings_data},
                ensure_ascii=False,
                indent=2,
            ),
        )
        zf.writestr(
            "domain_config.json",
            json.dumps(domain_config, ensure_ascii=False, indent=2),
        )

    zip_bytes = buf.getvalue()
    file_size = len(zip_bytes)

    # 4. 上传到 KB bucket
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"{_BACKUP_PREFIX}{timestamp}_{uuid.uuid4().hex[:8]}.zip"
    await storage_service.upload(file_name, zip_bytes, "application/zip", kb_id=kb_id)

    # 5. 创建备份记录
    backup = KbBackup(
        kb_id=kb_id,
        user_id=user_id,
        file_name=file_name,
        file_size=file_size,
        status="completed",
        item_counts=item_counts,
    )
    db.add(backup)
    await db.flush()

    logger.info(
        "KB 备份创建成功",
        kb_id=str(kb_id),
        backup_id=str(backup.id),
        file_size=file_size,
        item_counts=item_counts,
    )
    return backup


async def download_backup(
    db: AsyncSession,
    kb_id: uuid.UUID,
    backup_id: uuid.UUID,
) -> tuple[bytes, str]:
    """下载备份文件内容。

    Returns:
        tuple[bytes, str]: (ZIP 字节内容, 下载文件名)。
    """
    backup = await db.get(KbBackup, backup_id)
    if backup is None or backup.kb_id != kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message=f"备份 {backup_id} 不存在",
        )
    content = await storage_service.download(backup.file_name, kb_id=kb_id)
    download_name = backup.file_name.split("/")[-1]
    return content, download_name


async def delete_backup(
    db: AsyncSession,
    kb_id: uuid.UUID,
    backup_id: uuid.UUID,
) -> None:
    """删除备份（MinIO 对象 + DB 记录）。"""
    backup = await db.get(KbBackup, backup_id)
    if backup is None or backup.kb_id != kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message=f"备份 {backup_id} 不存在",
        )
    # 删除 MinIO 对象（best-effort）
    try:
        await storage_service.delete(backup.file_name, kb_id=kb_id)
    except Exception as err:  # noqa: BLE001
        logger.warning("删除备份 MinIO 对象失败", backup_id=str(backup_id), error=str(err))
    await db.delete(backup)


async def restore_backup(
    db: AsyncSession,
    kb_id: uuid.UUID,
    zip_bytes: bytes,
) -> dict:
    """从 ZIP 备份恢复数据到当前 KB。

    恢复策略：按唯一键去重（文档按 filename、Schema 按 name、术语按 term_name），
    已存在的跳过，避免覆盖现有数据。配置直接覆盖。

    Args:
        db: 异步数据库会话（已激活 RLS）。
        kb_id: 目标知识库 ID。
        zip_bytes: ZIP 备份文件字节内容。

    Returns:
        dict: 恢复统计（各资源恢复条数）。
    """
    logger.info("开始恢复 KB 备份", kb_id=str(kb_id))

    stats = {
        "documents": 0,
        "documents_skipped": 0,
        "schemas": 0,
        "schemas_skipped": 0,
        "terms": 0,
        "terms_skipped": 0,
        "domain_config": 0,
    }

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        config_data = json.loads(zf.read("config.json"))
        docs_data = json.loads(zf.read("documents.json"))
        schemas_data = json.loads(zf.read("schemas.json"))
        terms_data = json.loads(zf.read("terms.json"))
        domain_data = json.loads(zf.read("domain_config.json"))

    # 1. 恢复 KB 配置（直接覆盖）
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    ).scalar_one_or_none()
    if kb and isinstance(config_data.get("config"), dict):
        kb.config = config_data["config"]

    # 2. 恢复文档（按 filename 去重）
    existing_filenames = {
        row[0]
        for row in (
            await db.execute(select(Document.filename).where(Document.kb_id == kb_id))
        ).all()
    }
    for doc_data in docs_data:
        if doc_data["filename"] in existing_filenames:
            stats["documents_skipped"] += 1
            continue
        doc = Document(
            kb_id=kb_id,
            filename=doc_data["filename"],
            file_size=doc_data.get("file_size", 0),
            file_type=doc_data.get("file_type", ""),
            status=doc_data.get("status", "completed"),
            parsed_text=doc_data.get("parsed_text"),
            structured_data=doc_data.get("structured_data"),
            layout_data=doc_data.get("layout_data"),
        )
        db.add(doc)
        stats["documents"] += 1

    # 3. 恢复 Schema（按 name 去重，维护 parent_id 映射）
    existing_schema_names = {
        row[0]
        for row in (
            await db.execute(select(SchemaConfig.name).where(SchemaConfig.kb_id == kb_id))
        ).all()
    }
    id_map: dict[str, uuid.UUID] = {}  # 旧 ID → 新 ID
    for sch_data in schemas_data:
        if sch_data["name"] in existing_schema_names:
            stats["schemas_skipped"] += 1
            continue
        new_id = uuid.uuid4()
        old_id = sch_data.get("id", "")
        if old_id:
            id_map[old_id] = new_id
        sch = SchemaConfig(
            id=new_id,
            kb_id=kb_id,
            name=sch_data["name"],
            description=sch_data.get("description", ""),
            schema_definition=sch_data.get("schema_definition", {}),
            sample_fields=sch_data.get("sample_fields", {}),
            is_active=sch_data.get("is_active", True),
            sort_order=sch_data.get("sort_order", 0),
            is_template=sch_data.get("is_template", False),
        )
        db.add(sch)
        stats["schemas"] += 1

    # 设置 parent_id 映射（flush 后更新）
    if id_map:
        await db.flush()
        for sch_data in schemas_data:
            old_id = sch_data.get("id", "")
            parent_old = sch_data.get("parent_id")
            if old_id in id_map and parent_old and parent_old in id_map:
                sch = await db.get(SchemaConfig, id_map[old_id])
                if sch:
                    sch.parent_id = id_map[parent_old]

    # 4. 恢复术语（按 term_name 去重）
    existing_terms = {
        row[0]
        for row in (
            await db.execute(select(Term.term_name).where(Term.kb_id == kb_id))
        ).all()
    }
    term_id_map: dict[str, uuid.UUID] = {}
    for term_data in terms_data.get("terms", []):
        if term_data["term_name"] in existing_terms:
            stats["terms_skipped"] += 1
            continue
        new_id = uuid.uuid4()
        term_id_map[term_data.get("id", "")] = new_id
        term = Term(
            id=new_id,
            kb_id=kb_id,
            term_name=term_data["term_name"],
            standard_name=term_data.get("standard_name"),
            definition=term_data.get("definition", ""),
            synonyms=term_data.get("synonyms"),
            status=term_data.get("status", "active"),
            category=term_data.get("category"),
            standard_number=term_data.get("standard_number"),
        )
        db.add(term)
        stats["terms"] += 1

    # 5. 恢复领域配置（先清理再写入）
    await db.execute(sa_delete(KbCategory).where(KbCategory.kb_id == kb_id))
    await db.execute(sa_delete(KbRegexRule).where(KbRegexRule.kb_id == kb_id))
    await db.execute(sa_delete(KbFieldTemplate).where(KbFieldTemplate.kb_id == kb_id))
    await db.execute(sa_delete(KbDictConfig).where(KbDictConfig.kb_id == kb_id))

    for cat_data in domain_data.get("categories", []):
        db.add(
            KbCategory(
                kb_id=kb_id,
                name=cat_data["name"],
                extraction_class=cat_data.get("extraction_class", ""),
                description=cat_data.get("description", ""),
                is_active=cat_data.get("is_active", True),
                sort_order=cat_data.get("sort_order", 0),
                recall_filter_threshold=cat_data.get("recall_filter_threshold"),
            )
        )
    for rule_data in domain_data.get("regex_rules", []):
        db.add(
            KbRegexRule(
                kb_id=kb_id,
                name=rule_data.get("name", ""),
                pattern=rule_data.get("pattern", ""),
                description=rule_data.get("description", ""),
                enabled=rule_data.get("enabled", True),
                sort_order=rule_data.get("sort_order", 0),
            )
        )
    for ft_data in domain_data.get("field_templates", []):
        db.add(
            KbFieldTemplate(
                kb_id=kb_id,
                template_type=ft_data.get("template_type", "doc_info"),
                fields=ft_data.get("fields", []),
                prompt=ft_data.get("prompt"),
            )
        )
    for dc_data in domain_data.get("dict_configs", []):
        db.add(
            KbDictConfig(
                kb_id=kb_id,
                enabled=dc_data.get("enabled", True),
                sync_url=dc_data.get("sync_url"),
                sync_api_key=dc_data.get("sync_api_key"),
                sync_cron=dc_data.get("sync_cron"),
                match_threshold=dc_data.get("match_threshold", 0.6),
                whitelist_top_k=dc_data.get("whitelist_top_k", 20),
                validation_top_k=dc_data.get("validation_top_k", 1),
                validation_similarity_threshold=dc_data.get(
                    "validation_similarity_threshold", 0.6
                ),
                tables_mapping=dc_data.get("tables_mapping", {}),
            )
        )
    stats["domain_config"] = (
        len(domain_data.get("categories", []))
        + len(domain_data.get("regex_rules", []))
        + len(domain_data.get("field_templates", []))
        + len(domain_data.get("dict_configs", []))
    )

    logger.info(
        "KB 备份恢复完成",
        kb_id=str(kb_id),
        stats=stats,
        source_manifest=manifest.get("item_counts"),
    )
    return stats
