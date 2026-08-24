"""Add explicit closed-candle state for Phase 1B.1 hardening.

Revision ID: 20260824_0003
Revises: 20260824_0002
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0003"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("market_candles")}
    if "is_closed" not in columns:
        op.add_column(
            "market_candles",
            sa.Column("is_closed", sa.Boolean(), nullable=True, server_default=sa.true()),
        )
        op.execute(sa.text("UPDATE market_candles SET is_closed = true WHERE is_closed IS NULL"))
        op.alter_column("market_candles", "is_closed", nullable=False, server_default=sa.true())
    # Phase 1B derived rows created before close-time semantics are safely
    # rebuildable from market_candles and must not remain API-visible.
    op.execute(sa.text("DELETE FROM structure_events WHERE source = 'phase_1b_structure'"))
    op.execute(sa.text("DELETE FROM liquidity_events WHERE source = 'phase_1b_liquidity'"))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("market_candles")}
    if "is_closed" in columns:
        op.drop_column("market_candles", "is_closed")
