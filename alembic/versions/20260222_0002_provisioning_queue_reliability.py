"""Add provisioning queue reliability fields

Revision ID: 20260222_0002
Revises: 20260222_0001
Create Date: 2026-02-22 17:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260222_0002"
down_revision = "20260222_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provisioning_jobs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE provisioning_jobs SET idempotency_key = job_id WHERE idempotency_key IS NULL")
    op.execute("UPDATE provisioning_jobs SET available_at = created_at WHERE available_at IS NULL")

    with op.batch_alter_table("provisioning_jobs") as batch:
        batch.alter_column("idempotency_key", nullable=False)
        batch.alter_column("available_at", nullable=False)
        batch.create_index("ix_provisioning_jobs_idempotency_key", ["idempotency_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("provisioning_jobs") as batch:
        batch.drop_index("ix_provisioning_jobs_idempotency_key")
        batch.drop_column("available_at")
        batch.drop_column("max_attempts")
        batch.drop_column("idempotency_key")
