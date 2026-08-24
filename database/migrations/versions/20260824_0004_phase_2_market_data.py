"""Phase 2 real market data metadata, ingestion audit, and source-aware uniqueness.

Revision ID: 20260824_0004
Revises: 20260824_0003
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0004"
down_revision = "20260824_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("market_candles")}
    additions = {
        "tick_volume": sa.Column("tick_volume", sa.Numeric(24, 8), nullable=True),
        "spread": sa.Column("spread", sa.Numeric(24, 10), nullable=True),
        "provider": sa.Column("provider", sa.String(64), nullable=False, server_default="unknown"),
        "provider_timestamp": sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        "ingestion_time": sa.Column("ingestion_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        "source_timeframe": sa.Column("source_timeframe", sa.String(8), nullable=True),
        "target_timeframe": sa.Column("target_timeframe", sa.String(8), nullable=True),
        "resampling_method": sa.Column("resampling_method", sa.String(64), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("market_candles", column)

    uniques = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("market_candles")}
    if "uq_market_candle" in uniques:
        op.drop_constraint("uq_market_candle", "market_candles", type_="unique")
    if "uq_market_candle_source" not in uniques:
        op.create_unique_constraint(
            "uq_market_candle_source", "market_candles",
            ["symbol", "timeframe", "timestamp", "source"],
        )

    if not sa.inspect(bind).has_table("market_data_ingestions"):
        op.create_table(
            "market_data_ingestions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("timeframe", sa.String(8), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("request_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("request_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("rows_received", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gaps", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
        )
        op.create_index("ix_market_data_ingestions_provider_end", "market_data_ingestions", ["provider", "request_end"])
        op.create_index("ix_market_data_ingestions_symbol_tf_end", "market_data_ingestions", ["symbol", "timeframe", "request_end"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("market_data_ingestions"):
        op.drop_table("market_data_ingestions")
    uniques = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("market_candles")}
    if "uq_market_candle_source" in uniques:
        op.drop_constraint("uq_market_candle_source", "market_candles", type_="unique")
    if "uq_market_candle" not in uniques:
        op.create_unique_constraint("uq_market_candle", "market_candles", ["symbol", "timeframe", "timestamp"])
    columns = {column["name"] for column in sa.inspect(bind).get_columns("market_candles")}
    for name in ("resampling_method", "target_timeframe", "source_timeframe", "ingestion_time", "provider_timestamp", "provider", "spread", "tick_volume"):
        if name in columns:
            op.drop_column("market_candles", name)
