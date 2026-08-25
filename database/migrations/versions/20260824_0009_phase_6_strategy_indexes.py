"""Phase 6 strategy query indexes.

Revision ID: 20260824_0009
Revises: 20260824_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260824_0009"
down_revision = "20260824_0008"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_dca_events_timestamp", "dca_events", "timestamp"),
    ("ix_exit_decisions_timestamp", "exit_decisions", "timestamp"),
    ("ix_market_snapshots_symbol", "market_snapshots", "symbol"),
    ("ix_market_snapshots_timestamp", "market_snapshots", "timestamp"),
    ("ix_predictions_symbol", "predictions", "symbol"),
    ("ix_predictions_timestamp", "predictions", "timestamp"),
    ("ix_strategy_decisions_symbol", "strategy_decisions", "symbol"),
    ("ix_strategy_decisions_timestamp", "strategy_decisions", "timestamp"),
    ("ix_trade_setups_symbol", "trade_setups", "symbol"),
    ("ix_trade_setups_timestamp", "trade_setups", "timestamp"),
)

def upgrade():
    inspector = sa.inspect(op.get_bind())
    for name, table, column in INDEXES:
        existing = {item["name"] for item in inspector.get_indexes(table)}
        if name not in existing: op.create_index(name, table, [column])

def downgrade():
    inspector = sa.inspect(op.get_bind())
    for name, table, _ in reversed(INDEXES):
        existing = {item["name"] for item in inspector.get_indexes(table)}
        if name in existing: op.drop_index(name, table_name=table)
