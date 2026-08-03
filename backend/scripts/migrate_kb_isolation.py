"""知识库隔离架构迁移脚本 - 创建知识库体系与 RLS 行级安全。

执行步骤：
1. users 表扩展（is_superuser / avatar / last_login_at）
2. 创建 8 张新表（knowledge_bases / kb_members / knowledge_buckets + 5 领域配置表）
3. 现有业务表加 kb_id 列（documents/tasks/schema_configs/terms/term_mappings + 基础三表）
4. 创建默认知识库，现有数据挂载到默认 KB，业务表 kb_id 设 NOT NULL
5. 启用 RLS 行级安全策略（按 kb_id 强制隔离）

执行方式：
    cd backend && source venv/bin/activate && python scripts/migrate_kb_isolation.py

注意：
- 该迁移是幂等的，可重复执行。已存在的表/列/策略会跳过。
- RLS 策略对超级用户（superuser）不生效。当前若应用以 postgres 超级用户连接，
  RLS 作为合规策略就位，实际隔离由应用层 KBContext 强制 kb_id 过滤兜底；
  后续切换到非超级用户连接后 RLS 自动生效。
"""

import asyncio
import sys
import uuid
from pathlib import Path

# 加入 backend 目录到 sys.path，便于直接运行
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine


# 默认知识库（确定性 UUID，保证幂等）
DEFAULT_KB_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "hansondoc-default-kb")
DEFAULT_KB_NAME = "航天航空检测标准抽取"
DEFAULT_KB_DOMAIN = "material_testing"

# 需要加 kb_id（NOT NULL + RLS）的业务表
BUSINESS_TABLES = ["documents", "tasks", "schema_configs", "terms", "term_mappings"]
# 基础三表：kb_id 可空（NULL=全局共享），RLS 策略允许 NULL
SHARED_TABLES = ["sm_feature", "sm_item", "sm_method"]


# ============================================================
# 幂等检查工具
# ============================================================
async def table_exists(conn, table_name: str) -> bool:
    result = await conn.execute(
        text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}
    )
    return result.scalar() is not None


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    return result.scalar() is not None


async def policy_exists(conn, table_name: str, policy_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT 1 FROM pg_policies "
            "WHERE tablename = :table AND policyname = :policy"
        ),
        {"table": table_name, "policy": policy_name},
    )
    return result.scalar() is not None


async def not_null_constraint_exists(conn, table_name: str, column_name: str) -> bool:
    """检查某列是否已有 NOT NULL 约束。"""
    result = await conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    row = result.first()
    return row is not None and row[0] == "NO"


# ============================================================
# 步骤 1：users 表扩展
# ============================================================
async def extend_users_table(conn):
    """users 表加 is_superuser / avatar / last_login_at。"""
    if not await column_exists(conn, "users", "is_superuser"):
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN is_superuser BOOLEAN NOT NULL DEFAULT FALSE")
        )
        print("✓ users 表加 is_superuser 列")
    if not await column_exists(conn, "users", "avatar"):
        await conn.execute(text("ALTER TABLE users ADD COLUMN avatar VARCHAR(500)"))
        print("✓ users 表加 avatar 列")
    if not await column_exists(conn, "users", "last_login_at"):
        await conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP"))
        print("✓ users 表加 last_login_at 列")


# ============================================================
# 步骤 2：创建 8 张新表
# ============================================================
async def create_new_tables(conn):
    """创建知识库体系 8 张新表。"""
    # ---- knowledge_bases ----
    if not await table_exists(conn, "knowledge_bases"):
        await conn.execute(text("""
            CREATE TABLE knowledge_bases (
                id            UUID PRIMARY KEY,
                name          VARCHAR(100) NOT NULL,
                description   VARCHAR(500),
                domain_code   VARCHAR(64) NOT NULL,
                template_code VARCHAR(64),
                owner_id      UUID NOT NULL REFERENCES users(id),
                config        JSONB NOT NULL DEFAULT '{}',
                is_active     BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order    INTEGER NOT NULL DEFAULT 0,
                created_at    TIMESTAMP DEFAULT NOW(),
                updated_at    TIMESTAMP
            )
        """))
        await conn.execute(text("CREATE INDEX idx_knowledge_bases_domain ON knowledge_bases(domain_code)"))
        await conn.execute(text("CREATE INDEX idx_knowledge_bases_owner ON knowledge_bases(owner_id)"))
        print("✓ 创建表 knowledge_bases")

    # ---- kb_members ----
    if not await table_exists(conn, "kb_members"):
        await conn.execute(text("""
            CREATE TABLE kb_members (
                id         UUID PRIMARY KEY,
                kb_id      UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role       VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (kb_id, user_id)
            )
        """))
        await conn.execute(text("CREATE INDEX idx_kb_members_kb ON kb_members(kb_id)"))
        await conn.execute(text("CREATE INDEX idx_kb_members_user ON kb_members(user_id)"))
        print("✓ 创建表 kb_members")

    # ---- knowledge_buckets ----
    if not await table_exists(conn, "knowledge_buckets"):
        await conn.execute(text("""
            CREATE TABLE knowledge_buckets (
                id              UUID PRIMARY KEY,
                kb_id           UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE UNIQUE,
                bucket_name     VARCHAR(63) NOT NULL,
                access_key      VARCHAR(64) NOT NULL,
                secret_key_enc  VARCHAR(500) NOT NULL,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """))
        print("✓ 创建表 knowledge_buckets")

    # ---- kb_categories ----
    if not await table_exists(conn, "kb_categories"):
        await conn.execute(text("""
            CREATE TABLE kb_categories (
                id                       UUID PRIMARY KEY,
                kb_id                    UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                name                     VARCHAR(100) NOT NULL,
                extraction_class         VARCHAR(100) NOT NULL,
                description              VARCHAR(500),
                is_active                BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order               INTEGER NOT NULL DEFAULT 0,
                recall_filter_threshold  FLOAT,
                created_at               TIMESTAMP DEFAULT NOW(),
                updated_at               TIMESTAMP,
                UNIQUE (kb_id, name)
            )
        """))
        await conn.execute(text("CREATE INDEX idx_kb_categories_kb ON kb_categories(kb_id)"))
        print("✓ 创建表 kb_categories")

    # ---- kb_category_enums ----
    if not await table_exists(conn, "kb_category_enums"):
        await conn.execute(text("""
            CREATE TABLE kb_category_enums (
                id           UUID PRIMARY KEY,
                category_id  UUID NOT NULL REFERENCES kb_categories(id) ON DELETE CASCADE,
                field_name   VARCHAR(100) NOT NULL,
                enum_values  JSONB NOT NULL,
                UNIQUE (category_id, field_name)
            )
        """))
        await conn.execute(text("CREATE INDEX idx_kb_category_enums_cat ON kb_category_enums(category_id)"))
        print("✓ 创建表 kb_category_enums")

    # ---- kb_field_templates ----
    if not await table_exists(conn, "kb_field_templates"):
        await conn.execute(text("""
            CREATE TABLE kb_field_templates (
                id            UUID PRIMARY KEY,
                kb_id         UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                template_type VARCHAR(20) NOT NULL,
                fields        JSONB NOT NULL,
                prompt        TEXT,
                UNIQUE (kb_id, template_type)
            )
        """))
        await conn.execute(text("CREATE INDEX idx_kb_field_templates_kb ON kb_field_templates(kb_id)"))
        print("✓ 创建表 kb_field_templates")

    # ---- kb_regex_rules ----
    if not await table_exists(conn, "kb_regex_rules"):
        await conn.execute(text("""
            CREATE TABLE kb_regex_rules (
                id          UUID PRIMARY KEY,
                kb_id       UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                name        VARCHAR(64) NOT NULL,
                pattern     TEXT NOT NULL,
                description VARCHAR(500),
                enabled     BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMP DEFAULT NOW(),
                updated_at  TIMESTAMP,
                UNIQUE (kb_id, name)
            )
        """))
        await conn.execute(text("CREATE INDEX idx_kb_regex_rules_kb ON kb_regex_rules(kb_id)"))
        print("✓ 创建表 kb_regex_rules")

    # ---- kb_dict_configs ----
    if not await table_exists(conn, "kb_dict_configs"):
        await conn.execute(text("""
            CREATE TABLE kb_dict_configs (
                id                            UUID PRIMARY KEY,
                kb_id                         UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE UNIQUE,
                enabled                       BOOLEAN NOT NULL DEFAULT TRUE,
                sync_url                      VARCHAR(500),
                sync_api_key                  VARCHAR(200),
                sync_cron                     VARCHAR(50),
                match_threshold               FLOAT NOT NULL DEFAULT 0.6,
                whitelist_top_k               INTEGER NOT NULL DEFAULT 20,
                validation_top_k              INTEGER NOT NULL DEFAULT 1,
                validation_similarity_threshold FLOAT NOT NULL DEFAULT 0.6,
                tables_mapping                JSONB NOT NULL DEFAULT '{}',
                created_at                    TIMESTAMP DEFAULT NOW(),
                updated_at                    TIMESTAMP
            )
        """))
        print("✓ 创建表 kb_dict_configs")


# ============================================================
# 步骤 3：现有表加 kb_id 列（nullable，后续填充后再设 NOT NULL）
# ============================================================
async def add_kb_id_columns(conn):
    """业务表与基础三表加 kb_id 列（初始 nullable）。"""
    for table in BUSINESS_TABLES + SHARED_TABLES:
        if not await column_exists(conn, table, "kb_id"):
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN kb_id UUID REFERENCES knowledge_bases(id)")
            )
            await conn.execute(text(f"CREATE INDEX idx_{table}_kb ON {table}(kb_id)"))
            print(f"✓ {table} 加 kb_id 列")


# ============================================================
# 步骤 4：创建默认知识库 + 迁移现有数据
# ============================================================
async def get_or_create_superuser(conn) -> uuid.UUID:
    """选择或设置一个超级用户，返回其 ID。

    优先选 username='admin' 的用户；否则选第一个用户设为超管。
    """
    # 优先 admin
    result = await conn.execute(
        text("SELECT id FROM users WHERE username = 'admin' LIMIT 1")
    )
    admin_id = result.scalar_one_or_none()
    if admin_id is None:
        # 退而求其次：第一个用户
        result = await conn.execute(text("SELECT id FROM users ORDER BY created_at LIMIT 1"))
        admin_id = result.scalar_one_or_none()

    if admin_id is None:
        raise RuntimeError("users 表无用户，请先创建用户再执行迁移")

    await conn.execute(
        text("UPDATE users SET is_superuser = TRUE WHERE id = :uid"),
        {"uid": admin_id},
    )
    print(f"✓ 设置超级用户: {admin_id}")
    return admin_id


async def create_default_kb_and_migrate(conn):
    """创建默认知识库，迁移现有数据到默认 KB，业务表设 NOT NULL。"""
    # 1. 确保超级用户
    superuser_id = await get_or_create_superuser(conn)

    # 2. 创建默认知识库（幂等：按 id 查询）
    result = await conn.execute(
        text("SELECT id FROM knowledge_bases WHERE id = :kid"),
        {"kid": DEFAULT_KB_ID},
    )
    if result.scalar_one_or_none() is None:
        await conn.execute(
            text("""
                INSERT INTO knowledge_bases
                    (id, name, description, domain_code, template_code, owner_id, config, is_active, sort_order)
                VALUES
                    (:id, :name, :desc, :domain, 'material_testing', :owner, '{}'::jsonb, TRUE, 0)
            """),
            {
                "id": DEFAULT_KB_ID,
                "name": DEFAULT_KB_NAME,
                "desc": "默认知识库，迁移自现有数据（航天航空检测标准抽取）",
                "domain": DEFAULT_KB_DOMAIN,
                "owner": superuser_id,
            },
        )
        print(f"✓ 创建默认知识库: {DEFAULT_KB_NAME} (id={DEFAULT_KB_ID})")

    # 3. 创建 owner 成员关系（幂等）
    await conn.execute(
        text("""
            INSERT INTO kb_members (id, kb_id, user_id, role)
            VALUES (:mid, :kid, :uid, 'owner')
            ON CONFLICT (kb_id, user_id) DO NOTHING
        """),
        {"mid": uuid.uuid4(), "kid": DEFAULT_KB_ID, "uid": superuser_id},
    )
    print("✓ 默认知识库 owner 成员关系已建立")

    # 4. 现有业务表数据填充默认 kb_id（NULL 的行填默认 KB）
    for table in BUSINESS_TABLES:
        await conn.execute(
            text(f"UPDATE {table} SET kb_id = :kid WHERE kb_id IS NULL"),
            {"kid": DEFAULT_KB_ID},
        )

    # 5. 业务表 kb_id 设 NOT NULL（基础三表保持 nullable）
    for table in BUSINESS_TABLES:
        if not await not_null_constraint_exists(conn, table, "kb_id"):
            await conn.execute(
                text(f"ALTER TABLE {table} ALTER COLUMN kb_id SET NOT NULL")
            )
            print(f"✓ {table}.kb_id 设 NOT NULL")

    # 6. documents.owner_id 填充（NULL 的行填超管）
    if await column_exists(conn, "documents", "owner_id"):
        await conn.execute(
            text("UPDATE documents SET owner_id = :uid WHERE owner_id IS NULL"),
            {"uid": superuser_id},
        )


# ============================================================
# 步骤 5：启用 RLS 行级安全策略
# ============================================================
async def enable_rls(conn):
    """启用 RLS + 创建行级安全策略。

    业务表策略：只能看到 current_setting('app.current_kb') 指定的 KB 行。
    基础三表策略：kb_id IS NULL（全局共享）OR 当前 KB。
    """
    # 业务表 RLS
    for table in BUSINESS_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        policy = "kb_isolation"
        if not await policy_exists(conn, table, policy):
            await conn.execute(text(
                f"CREATE POLICY {policy} ON {table} "
                f"USING (kb_id::text = current_setting('app.current_kb', true))"
            ))
        print(f"✓ {table} 启用 RLS 策略")

    # 基础三表 RLS（允许全局共享行）
    for table in SHARED_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        policy = "kb_isolation_shared"
        if not await policy_exists(conn, table, policy):
            await conn.execute(text(
                f"CREATE POLICY {policy} ON {table} "
                f"USING (kb_id IS NULL OR kb_id::text = current_setting('app.current_kb', true))"
            ))
        print(f"✓ {table} 启用 RLS 策略（含全局共享）")


# ============================================================
# 主流程
# ============================================================
async def main():
    print("=" * 60)
    print("HansonDOC RAG 知识库隔离架构迁移")
    print("=" * 60)

    async with engine.begin() as conn:
        print("\n[步骤 1] 扩展 users 表")
        await extend_users_table(conn)

        print("\n[步骤 2] 创建知识库新表")
        await create_new_tables(conn)

        print("\n[步骤 3] 现有表加 kb_id 列")
        await add_kb_id_columns(conn)

        print("\n[步骤 4] 创建默认知识库 + 迁移现有数据")
        await create_default_kb_and_migrate(conn)

        print("\n[步骤 5] 启用 RLS 行级安全策略")
        await enable_rls(conn)

    await engine.dispose()
    print("\n" + "=" * 60)
    print("✅ 迁移完成")
    print(f"   默认知识库 ID: {DEFAULT_KB_ID}")
    print("   提示: 应用层请在请求开始时执行 SET LOCAL app.current_kb = '<kb_id>' 激活 RLS")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
