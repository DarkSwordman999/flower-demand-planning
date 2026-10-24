"""Каналы продаж (Р-4): маркетплейсы и другие сайты со своим ключом API

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("price_factor", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("key_hash"),
    )
    with op.batch_alter_table("online_orders") as b:
        b.add_column(sa.Column("channel_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_online_orders_channel_id", "sales_channels", ["channel_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("online_orders") as b:
        b.drop_constraint("fk_online_orders_channel_id", type_="foreignkey")
        b.drop_column("channel_id")
    op.drop_table("sales_channels")
