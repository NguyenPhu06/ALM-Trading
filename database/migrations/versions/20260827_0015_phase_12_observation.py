"""Phase 12 observation and live-market validation store.

Revision ID: 20260827_0015; Revises: 20260826_0014

Forward-observation records only. `execution_simulations.orders_sent` exists so
the audit shows explicitly that no order was ever placed. No credential columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0015"
down_revision = "20260826_0014"
branch_labels = None
depends_on = None

TABLES = (
    "observation_performance", "mt5_health_events", "system_health",
    "execution_simulations", "feature_snapshots", "observation_market_snapshots",
)


def upgrade() -> None:
    op.create_table(
        "observation_market_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cycle_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("regime", sa.String(16)),
        sa.Column("session", sa.String(32)),
        sa.Column("mid_price", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("source", sa.String(32), nullable=False, server_default="mt5"),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
    )
    for column in ("cycle_id", "timestamp", "symbol"):
        op.create_index(f"ix_observation_market_snapshots_{column}",
                        "observation_market_snapshots", [column])

    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cycle_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("regime", sa.String(16)),
        sa.Column("signal", sa.String(16)),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="mt5"),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
    )
    for column in ("cycle_id", "timestamp", "symbol"):
        op.create_index(f"ix_feature_snapshots_{column}", "feature_snapshots", [column])

    op.create_table(
        "execution_simulations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("simulation_id", sa.String(64), nullable=False),
        sa.Column("cycle_id", sa.String(64)),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("signal", sa.String(16), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("execution", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("observation_mode", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("orders_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("simulation_json", sa.JSON, nullable=False),
    )
    for column in ("simulation_id", "cycle_id", "timestamp", "symbol"):
        op.create_index(f"ix_execution_simulations_{column}", "execution_simulations", [column])

    op.create_table(
        "system_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("cycle_id", sa.String(64)),
        sa.Column("last_error", sa.Text),
        sa.Column("health_json", sa.JSON, nullable=False),
    )
    for column in ("timestamp", "state", "cycle_id"):
        op.create_index(f"ix_system_health_{column}", "system_health", [column])

    op.create_table(
        "mt5_health_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("login_masked", sa.String(32)),
        sa.Column("broker", sa.String(64)),
        sa.Column("server", sa.String(128)),
        sa.Column("account_type", sa.String(16)),
        sa.Column("terminal_build", sa.Integer),
        sa.Column("reasons", sa.Text),
        sa.Column("event_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_health_events_timestamp", "mt5_health_events", ["timestamp"])
    op.create_index("ix_mt5_health_events_status", "mt5_health_events", ["status"])

    op.create_table(
        "observation_performance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cycle_id", sa.String(64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("signal", sa.String(16), nullable=False),
        sa.Column("entry", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("mae", sa.Float),
        sa.Column("mfe", sa.Float),
        sa.Column("hypothetical_pnl", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("session", sa.String(32)),
        sa.Column("regime", sa.String(16)),
        sa.Column("nn_confidence", sa.Float),
        sa.Column("strategy_confidence", sa.Float),
        sa.Column("dca_state", sa.String(32)),
        sa.Column("observed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("record_json", sa.JSON, nullable=False),
    )
    for column in ("cycle_id", "opened_at", "symbol"):
        op.create_index(f"ix_observation_performance_{column}", "observation_performance", [column])


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
