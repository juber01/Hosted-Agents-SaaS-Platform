"""Rename customer_id to customer_user_id in entitlements

Revision ID: 20260223_0004
Revises: 20260223_0003
Create Date: 2026-02-23 15:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260223_0004"
down_revision = "20260223_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customer_agent_entitlements") as batch:
        batch.alter_column(
            "customer_id",
            new_column_name="customer_user_id",
            existing_type=sa.String(length=100),
            existing_nullable=False,
        )

    op.drop_index(
        "ix_customer_agent_entitlements_tenant_customer",
        table_name="customer_agent_entitlements",
    )
    op.create_index(
        "ix_customer_agent_entitlements_tenant_customer_user",
        "customer_agent_entitlements",
        ["tenant_id", "customer_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_agent_entitlements_tenant_customer_user",
        table_name="customer_agent_entitlements",
    )

    with op.batch_alter_table("customer_agent_entitlements") as batch:
        batch.alter_column(
            "customer_user_id",
            new_column_name="customer_id",
            existing_type=sa.String(length=100),
            existing_nullable=False,
        )
    op.create_index(
        "ix_customer_agent_entitlements_tenant_customer",
        "customer_agent_entitlements",
        ["tenant_id", "customer_id"],
        unique=False,
    )
