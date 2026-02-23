"""Add tenant agents and customer entitlements

Revision ID: 20260223_0003
Revises: 20260222_0002
Create Date: 2026-02-23 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260223_0003"
down_revision = "20260222_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_agents",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "agent_id"),
    )
    op.create_index("ix_tenant_agents_tenant_id", "tenant_agents", ["tenant_id"], unique=False)

    op.create_table(
        "customer_agent_entitlements",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=100), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "customer_id", "agent_id"),
    )
    op.create_index(
        "ix_customer_agent_entitlements_tenant_customer",
        "customer_agent_entitlements",
        ["tenant_id", "customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_agent_entitlements_tenant_agent",
        "customer_agent_entitlements",
        ["tenant_id", "agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_customer_agent_entitlements_tenant_agent", table_name="customer_agent_entitlements")
    op.drop_index("ix_customer_agent_entitlements_tenant_customer", table_name="customer_agent_entitlements")
    op.drop_table("customer_agent_entitlements")

    op.drop_index("ix_tenant_agents_tenant_id", table_name="tenant_agents")
    op.drop_table("tenant_agents")
