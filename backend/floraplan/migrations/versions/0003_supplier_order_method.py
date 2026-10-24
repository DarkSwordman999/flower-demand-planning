"""Способ отправки заказа поставщику (Р-4): e-mail или API поставщика

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("suppliers") as b:
        b.add_column(sa.Column("order_method", sa.String(length=20), nullable=False, server_default="email"))
        b.add_column(sa.Column("order_url", sa.String(length=300), nullable=False, server_default=""))
        b.add_column(sa.Column("order_api_key", sa.String(length=200), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("suppliers") as b:
        b.drop_column("order_api_key")
        b.drop_column("order_url")
        b.drop_column("order_method")
