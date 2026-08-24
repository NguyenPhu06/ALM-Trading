"""Add causal event timestamps for Phase 1B.

Revision ID: 20260824_0002
Revises: 20260824_0001
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None


def _upgrade_table(table: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "event_timestamp" not in columns:
        op.add_column(table, sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET event_timestamp = timestamp"))
        op.alter_column(table, "event_timestamp", nullable=False)
    if "confirmation_timestamp" not in columns:
        op.add_column(table, sa.Column("confirmation_timestamp", sa.DateTime(timezone=True), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
    index_name = f"ix_{table}_event_timestamp"
    if index_name not in indexes:
        op.create_index(index_name, table, ["event_timestamp"])


def upgrade() -> None:
    _upgrade_table("structure_events")
    _upgrade_table("liquidity_events")


def downgrade() -> None:
    for table in ("liquidity_events", "structure_events"):
        bind = op.get_bind()
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        index_name = f"ix_{table}_event_timestamp"
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "confirmation_timestamp" in columns:
            op.drop_column(table, "confirmation_timestamp")
        if "event_timestamp" in columns:
            op.drop_column(table, "event_timestamp")
