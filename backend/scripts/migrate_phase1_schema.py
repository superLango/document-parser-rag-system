"""阶段1 数据库 schema 迁移脚本（幂等）。

直接通过 asyncpg 执行 ALTER TABLE / CREATE TABLE，使用 IF NOT EXISTS 保证幂等。
覆盖：
- users 表新增 9 列（profile + 安全 + 软删除）
- terms 表新增 5 列（category/standard_number/updated_at/reviewed_by/reviewed_at）
- tasks 表新增 5 列（task_type/started_at/error_trace/retry_count/parent_task_id）
- 新建 audit_logs / password_reset_tokens / password_history 表
"""
import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:change_me@localhost:5432/docparser",
    )
    # 转换 asyncpg 不支持的 +asyncpg scheme
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        # ---------- users 表扩展 ----------
        user_cols = [
            ("full_name", "VARCHAR(100)"),
            ("phone", "VARCHAR(30)"),
            ("department", "VARCHAR(100)"),
            ("notes", "VARCHAR(500)"),
            ("password_changed_at", "TIMESTAMP"),
            ("failed_login_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("locked_until", "TIMESTAMP"),
            ("last_login_ip", "VARCHAR(64)"),
            ("deleted_at", "TIMESTAMP"),
        ]
        for col, typ in user_cols:
            await conn.execute(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typ}"
            )

        # ---------- terms 表扩展 ----------
        term_cols = [
            ("category", "VARCHAR(50)"),
            ("standard_number", "VARCHAR(100)"),
            ("updated_at", "TIMESTAMP"),
            ("reviewed_by", "UUID REFERENCES users(id)"),
            ("reviewed_at", "TIMESTAMP"),
        ]
        for col, typ in term_cols:
            await conn.execute(
                f"ALTER TABLE terms ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_terms_category ON terms(category)"
        )

        # ---------- tasks 表扩展 ----------
        task_cols = [
            ("task_type", "VARCHAR(30) DEFAULT 'parse' NOT NULL"),
            ("started_at", "TIMESTAMP"),
            ("error_trace", "TEXT"),
            ("retry_count", "INTEGER DEFAULT 0 NOT NULL"),
            ("parent_task_id", "VARCHAR(36) REFERENCES tasks(id)"),
        ]
        for col, typ in task_cols:
            await conn.execute(
                f"ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_task_type ON tasks(task_type)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)"
        )

        # ---------- 新建 audit_logs 表 ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID REFERENCES users(id),
                username VARCHAR(50),
                kb_id UUID,
                action VARCHAR(64) NOT NULL,
                resource_type VARCHAR(32),
                resource_id VARCHAR(64),
                method VARCHAR(10),
                path VARCHAR(500),
                status_code INTEGER,
                ip VARCHAR(64),
                user_agent VARCHAR(500),
                details JSONB,
                trace_id VARCHAR(64),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_kb ON audit_logs(kb_id)"
        )

        # ---------- 新建 password_reset_tokens 表 ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token VARCHAR(255) NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE NOT NULL,
                created_by UUID REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prt_user ON password_reset_tokens(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prt_token ON password_reset_tokens(token)"
        )

        # ---------- 新建 password_history 表 ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS password_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                hashed_password VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ph_user ON password_history(user_id)"
        )

        print("✅ 阶段1 数据库迁移完成")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
