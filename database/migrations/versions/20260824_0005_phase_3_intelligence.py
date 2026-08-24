"""Phase 3 market intelligence snapshots.

Revision ID: 20260824_0005
Revises: 20260824_0004
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0005"
down_revision = "20260824_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("market_intelligence_snapshots"):
        return
    op.create_table(
        "market_intelligence_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False, server_default="MTF"),
        sa.Column("market_candle_id", sa.Integer(), sa.ForeignKey("market_candles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("calculation_version", sa.String(32), nullable=False),
        sa.Column("bias", sa.String(32), nullable=False),
        sa.Column("trade_state", sa.String(32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("feature_vector_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "timeframe", "event_timestamp", "calculation_version", name="uq_market_intelligence_snapshot"),
    )
    op.create_index(
        "ix_intelligence_symbol_tf_timestamp", "market_intelligence_snapshots",
        ["symbol", "timeframe", "event_timestamp"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("market_intelligence_snapshots"):
        op.drop_table("market_intelligence_snapshots")
