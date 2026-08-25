"""Phase 6 research strategy records.

Revision ID: 20260824_0008
Revises: 20260824_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260824_0008"
down_revision = "20260824_0007"
branch_labels = None
depends_on = None

TABLES = {
    "market_snapshots": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("symbol", sa.String(32), nullable=False), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("feature_version", sa.String(64), nullable=False), sa.Column("snapshot_json", sa.JSON, nullable=False)],
    "trade_setups": [sa.Column("setup_id", sa.String(64), primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("symbol", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("direction", sa.String(16), nullable=False), sa.Column("score", sa.Float, nullable=False), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("feature_version", sa.String(64), nullable=False), sa.Column("model_version", sa.String(64)), sa.Column("setup_json", sa.JSON, nullable=False)],
    "strategy_decisions": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("symbol", sa.String(32), nullable=False), sa.Column("setup_id", sa.String(64)), sa.Column("decision", sa.String(32), nullable=False), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("decision_json", sa.JSON, nullable=False)],
    "predictions": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("symbol", sa.String(32), nullable=False), sa.Column("model_version", sa.String(64), nullable=False), sa.Column("feature_version", sa.String(64), nullable=False), sa.Column("prediction_json", sa.JSON, nullable=False)],
    "dca_events": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("setup_id", sa.String(64)), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("event_json", sa.JSON, nullable=False)],
    "exit_decisions": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("setup_id", sa.String(64)), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("decision_json", sa.JSON, nullable=False)],
    "strategy_backtests": [sa.Column("id", sa.Integer, primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("strategy_version", sa.String(64), nullable=False), sa.Column("feature_version", sa.String(64), nullable=False), sa.Column("model_version", sa.String(64)), sa.Column("result_json", sa.JSON, nullable=False)],
}

def upgrade():
    inspector = sa.inspect(op.get_bind())
    for name, columns in TABLES.items():
        if not inspector.has_table(name): op.create_table(name, *columns)

def downgrade():
    inspector = sa.inspect(op.get_bind())
    for name in reversed(tuple(TABLES)):
        if inspector.has_table(name): op.drop_table(name)
