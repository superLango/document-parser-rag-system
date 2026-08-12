"""L4 边界：M34-S1 抽取配置存储约束。"""

import uuid

import pytest
from qa.fixtures.indexing_helpers import create_kb_via_api
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

from app.models.extraction import (
    KbScript,
    PromptContent,
    PromptTemplate,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)


async def _setup_kb(client, super_token, name, db_session):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    return kb_id


async def test_schema_template_duplicate_name(client, super_token, db_session):
    """L4M34-S1-01：同 KB 模板重名违反唯一索引。"""
    kb_id = await _setup_kb(client, super_token, "S9模板唯一", db_session)
    db_session.add(SchemaTemplate(kb_id=kb_id, name="模板A"))
    await db_session.commit()
    db_session.add(SchemaTemplate(kb_id=kb_id, name="模板A"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_schema_field_duplicate_name(client, super_token, db_session):
    """L4M34-S1-02：同类别字段重名违反唯一索引。"""
    kb_id = await _setup_kb(client, super_token, "S9字段唯一", db_session)
    tpl = SchemaTemplate(kb_id=kb_id, name="模板B")
    db_session.add(tpl)
    await db_session.flush()
    cat = SchemaCategory(kb_id=kb_id, template_id=tpl.id, name="类别")
    db_session.add(cat)
    await db_session.commit()
    db_session.add(SchemaField(kb_id=kb_id, category_id=cat.id, name="抗拉强度"))
    db_session.add(SchemaField(kb_id=kb_id, category_id=cat.id, name="抗拉强度"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_script_duplicate_folder_name(client, super_token, db_session):
    """L4M34-S1-03：同目录脚本重名违反唯一索引。"""
    kb_id = await _setup_kb(client, super_token, "S9脚本唯一", db_session)
    db_session.add(KbScript(kb_id=kb_id, folder="post", name="clean"))
    await db_session.commit()
    db_session.add(KbScript(kb_id=kb_id, folder="post", name="clean"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_prompt_simple_content_unique(client, super_token, db_session):
    """L4M34-S1-04：simple Prompt 仅允许一条内容（部分唯一索引）。"""
    kb_id = await _setup_kb(client, super_token, "S9Prompt唯一", db_session)
    prompt = PromptTemplate(kb_id=kb_id, name="简单Prompt", scope="simple")
    db_session.add(prompt)
    await db_session.commit()
    db_session.add(PromptContent(kb_id=kb_id, prompt_id=prompt.id, category_id=None, system_prompt="s1"))
    await db_session.commit()
    db_session.add(PromptContent(kb_id=kb_id, prompt_id=prompt.id, category_id=None, system_prompt="s2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
