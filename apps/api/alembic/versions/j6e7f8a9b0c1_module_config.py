"""knowledge base module config

Revision ID: j6e7f8a9b0c1
Revises: i5f6a7b8c9d0
Create Date: 2026-11-06

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j6e7f8a9b0c1"
down_revision: Union[str, None] = "i5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 内建模块工作区标记，例如 {"module": "standard_split", "builtin": true}
    op.add_column(
        "knowledge_bases",
        sa.Column("config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.drop_column("config")
