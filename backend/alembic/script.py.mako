"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Alembic 修订版本标识
revision: str = ${repr(up_revision)}
# 前一版本标识（回滚目标）
down_revision: Union[str, None] = ${repr(down_revision)}
# 分支标识
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
# 依赖版本
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
