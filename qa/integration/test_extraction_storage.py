"""L2 集成：M34-S1 抽取配置迁移产物与 ORM 读写。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app.models.extraction import (
    KbScript,
    PromptContent,
    PromptTemplate,
    RuleGroup,
    RuleGroupItem,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)

TABLES = [
    "schema_templates", "schema_categories", "schema_fields",
    "prompt_templates", "prompt_content", "rule_groups",
    "rule_group_items", "kb_scripts",
]


async def test_migration_artifacts(client, super_token, db_session):
    """L2M34-S1-01：迁移产物（表/索引/RLS 策略）齐备。"""
    rows = (await db_session.execute(sa_text(
        "select tablename from pg_tables where schemaname='public' "
        "and tablename in ('schema_templates','schema_categories','schema_fields',"
        "'prompt_templates','prompt_content','rule_groups','rule_group_items','kb_scripts')"
    ))).scalars().all()
    assert set(rows) == set(TABLES)
    policies = (await db_session.execute(sa_text(
        "select count(*) from pg_policies where tablename in ('schema_templates','schema_categories',"
        "'schema_fields','prompt_templates','prompt_content','rule_groups','rule_group_items','kb_scripts')"
    ))).scalar()
    assert policies == 32  # 8 表 × 4 策略
    idx = (await db_session.execute(sa_text(
        "select indexname from pg_indexes where tablename='schema_templates'"
    ))).scalars().all()
    assert "uq_schema_templates_kb_name" in idx


async def test_orm_write_read_and_cascade(client, super_token, db_session):
    """L2M34-S1-02：ORM 写入/读取；模板→类别→字段、规则组、Prompt 级联删除。"""
    kb = await create_kb_via_api(client, super_token, "S9抽取模型")
    kb_id = uuid.UUID(kb["id"])
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    tpl = SchemaTemplate(kb_id=kb_id, name="材料模板", description="d", is_active=True)
    db_session.add(tpl)
    await db_session.flush()
    cat = SchemaCategory(
        kb_id=kb_id, template_id=tpl.id, name="室温拉伸", return_type="array",
        name_source="term_base", name_term_field="term_name",
        query_sources=[{"label": "材料", "term_base_id": str(uuid.uuid4()), "value_field": "name"}],
    )
    db_session.add(cat)
    await db_session.flush()
    fld = SchemaField(kb_id=kb_id, category_id=cat.id, name="抗拉强度", type="string", required=True)
    db_session.add(fld)

    prompt = PromptTemplate(kb_id=kb_id, name="材料Prompt", scope="schema", schema_template_id=tpl.id, category_ids=[str(cat.id)])
    db_session.add(prompt)
    await db_session.flush()
    pc = PromptContent(kb_id=kb_id, prompt_id=prompt.id, category_id=cat.id, system_prompt="sys", user_prompt="user")
    db_session.add(pc)

    group = RuleGroup(kb_id=kb_id, name="后处理组", enabled=True)
    db_session.add(group)
    await db_session.flush()
    item = RuleGroupItem(kb_id=kb_id, group_id=group.id, category_id=cat.id, script_name="clean", params={"x": 1})
    db_session.add(item)

    script = KbScript(kb_id=kb_id, folder="post", name="clean", code="def run(args): return args", enabled=True)
    db_session.add(script)
    await db_session.commit()

    # 读取
    got_cat = (await db_session.execute(select(SchemaCategory).where(SchemaCategory.id == cat.id))).scalar_one()
    assert got_cat.name_source == "term_base"
    assert got_cat.query_sources[0]["value_field"] == "name"
    assert (await db_session.execute(select(SchemaField).where(SchemaField.id == fld.id))).scalar_one().name == "抗拉强度"
    assert (await db_session.execute(select(PromptContent).where(PromptContent.id == pc.id))).scalar_one().user_prompt == "user"
    assert (await db_session.execute(select(RuleGroupItem).where(RuleGroupItem.id == item.id))).scalar_one().script_name == "clean"
    assert (await db_session.execute(select(KbScript).where(KbScript.id == script.id))).scalar_one().folder == "post"

    # 级联：删模板 → 类别/字段消失；删规则组 → 项消失；删 prompt → content 消失
    await db_session.delete(tpl)
    await db_session.execute(sa_text("delete from rule_groups where id=:g").bindparams(g=group.id))
    await db_session.execute(sa_text("delete from prompt_templates where id=:p").bindparams(p=prompt.id))
    await db_session.commit()
    assert (await db_session.execute(select(SchemaCategory).where(SchemaCategory.id == cat.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(SchemaField).where(SchemaField.id == fld.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(RuleGroupItem).where(RuleGroupItem.id == item.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(PromptContent).where(PromptContent.id == pc.id))).scalar_one_or_none() is None
