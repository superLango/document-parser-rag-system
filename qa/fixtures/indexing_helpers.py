"""M24/M25 索引模块共享测试辅助：KB/文档/RLS 上下文构造。"""

from __future__ import annotations

import uuid

from sqlalchemy import text as sa_text


async def create_kb_via_api(client, super_token, name: str) -> dict:
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def create_document_row(
    db, kb_id: uuid.UUID, filename: str = "idx.pdf", layout_path: str | None = None
) -> uuid.UUID:
    """以超管上下文插入 documents 行（索引表 FK 依赖）。

    layout_path 非空时视为已解析完成（可进入索引）。
    """
    from sqlalchemy import insert

    from app.models.document import Document

    await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    stmt = (
        insert(Document)
        .values(
            kb_id=kb_id,
            filename=filename,
            object_key=f"kb-{kb_id.hex}/originals/{filename}",
            sha256="a" * 64,
            status="completed",
            process_status="completed",
            page_count=2,
            layout_path=layout_path,
        )
        .returning(Document.id)
    )
    doc_id = (await db.execute(stmt)).scalar_one()
    await db.commit()
    return doc_id


async def ensure_test_role(db, role_name: str) -> None:
    """幂等创建非超管测试角色。"""
    from sqlalchemy.exc import ProgrammingError

    try:
        await db.execute(sa_text(f"CREATE ROLE {role_name} NOSUPERUSER LOGIN"))
        await db.commit()
    except ProgrammingError:
        await db.rollback()


async def grant_table_permissions(db, role_name: str, tables: list[str]) -> None:
    """授权测试角色访问索引三表及策略函数依赖表。"""
    await db.execute(sa_text("GRANT USAGE ON SCHEMA public TO " + role_name))
    for t in tables:
        await db.execute(
            sa_text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {role_name}")
        )
    # 策略函数 hansondoc_kb_effective_role 依赖以下表
    for t in (
        "knowledge_bases",
        "kb_members",
        "kb_group_access",
        "group_members",
        "users",
        "documents",
    ):
        await db.execute(sa_text(f"GRANT SELECT ON {t} TO {role_name}"))
    # pgvector 类型使用权限（新类型默认 PUBLIC 无权限）
    await db.execute(sa_text(f"GRANT USAGE ON TYPE vector TO {role_name}"))
    await db.commit()


async def set_rls_context(db, kb_id: uuid.UUID | None, user_id: uuid.UUID | None) -> None:
    """设置/清空 RLS 上下文（is_superuser 与 current_kb、user_id）。"""
    await db.execute(sa_text("SELECT set_config('app.is_superuser', '', true)"))
    await db.execute(
        sa_text("SELECT set_config('app.current_kb', :kb, true)"),
        {"kb": str(kb_id) if kb_id else ""},
    )
    await db.execute(
        sa_text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )


async def upsert_kb_member(db, kb_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    """直接写入 kb_members 行，构造 RLS 有效成员上下文。"""
    from sqlalchemy import delete, insert

    from app.models.knowledge_base import KbMember

    await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await db.execute(delete(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user_id))
    await db.execute(
        insert(KbMember).values(
            kb_id=kb_id, user_id=user_id, role=role, status="active"
        )
    )
    await db.commit()
