"""002_add_process_status: 新增一体化公开接口流程状态字段

为 documents 表添加两列，支撑一体化公开接口（上传 PDF → 异步 OCR+抽取 → 凭 task_id 查状态/取结果）：

- ``process_status``：一体化流程状态，独立于 ``status`` / ``extraction_status``。
  避免编排任务串联 OCR+抽取时 Task.status 在 completed↔running 间抖动导致状态查询不准。
  取值：queued / ocr_processing / ocr_done / extracting / completed / failed
- ``process_task_id``：一体化编排任务 ID（雪花 ID），用于公开接口凭 task_id 反查文档与结果。

revision: 002_add_process_status
down_revision: 001_initial
"""

from alembic import op
import sqlalchemy as sa

revision = "002_add_process_status"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("process_status", sa.String(30), nullable=True))
    op.add_column("documents", sa.Column("process_task_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_documents_process_task_id", "documents", ["process_task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_process_task_id", table_name="documents")
    op.drop_column("documents", "process_task_id")
    op.drop_column("documents", "process_status")
