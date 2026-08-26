"""Phase 10 MT5 read-only observation store.

Revision ID: 20260826_0013; Revises: 20260825_0012

No credential is persisted: there is no password, token or secret column here.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260826_0013"
down_revision = "20260825_0012"
branch_labels = None
depends_on = None

TABLES = (
    "mt5_data_quality_events", "mt5_connection_events", "mt5_order_snapshots",
    "mt5_position_snapshots", "mt5_tick_snapshots", "mt5_symbol_snapshots",
    "mt5_account_snapshots", "mt5_accounts",
)


def upgrade() -> None:
    op.create_table(
        "mt5_accounts",
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("login_masked", sa.String(32), nullable=False),
        sa.Column("broker", sa.String(64), nullable=False),
        sa.Column("server", sa.String(128)),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("trade_mode", sa.String(16), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("leverage", sa.Integer),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mt5_account_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("login_masked", sa.String(32), nullable=False),
        sa.Column("broker", sa.String(64), nullable=False),
        sa.Column("server", sa.String(128)),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("balance", sa.Float, nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("margin", sa.Float, nullable=False),
        sa.Column("free_margin", sa.Float, nullable=False),
        sa.Column("margin_level", sa.Float, nullable=False),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_account_snapshots_timestamp", "mt5_account_snapshots", ["timestamp"])
    op.create_index("ix_mt5_account_snapshots_account_id", "mt5_account_snapshots", ["account_id"])

    op.create_table(
        "mt5_symbol_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("broker_symbol", sa.String(64), nullable=False),
        sa.Column("digits", sa.Integer),
        sa.Column("point", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("visible", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_symbol_snapshots_timestamp", "mt5_symbol_snapshots", ["timestamp"])
    op.create_index("ix_mt5_symbol_snapshots_symbol", "mt5_symbol_snapshots", ["symbol"])

    op.create_table(
        "mt5_tick_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("broker_symbol", sa.String(64)),
        sa.Column("bid", sa.Float),
        sa.Column("ask", sa.Float),
        sa.Column("last", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("spread_state", sa.String(16)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("tick_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_tick_snapshots_timestamp", "mt5_tick_snapshots", ["timestamp"])
    op.create_index("ix_mt5_tick_snapshots_symbol", "mt5_tick_snapshots", ["symbol"])

    op.create_table(
        "mt5_position_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket", sa.BigInteger, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("profit", sa.Float, nullable=False),
        sa.Column("swap", sa.Float, nullable=False),
        sa.Column("commission", sa.Float, nullable=False),
        sa.Column("magic_number", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("comment", sa.String(255)),
        sa.Column("ownership", sa.String(16), nullable=False),
        sa.Column("position_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_position_snapshots_timestamp", "mt5_position_snapshots", ["timestamp"])
    op.create_index("ix_mt5_position_snapshots_ticket", "mt5_position_snapshots", ["ticket"])
    op.create_index("ix_mt5_position_snapshots_symbol", "mt5_position_snapshots", ["symbol"])

    op.create_table(
        "mt5_order_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket", sa.BigInteger, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("order_type", sa.String(32)),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("price_open", sa.Float, nullable=False),
        sa.Column("state", sa.String(32)),
        sa.Column("magic_number", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("ownership", sa.String(16), nullable=False),
        sa.Column("order_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_order_snapshots_timestamp", "mt5_order_snapshots", ["timestamp"])
    op.create_index("ix_mt5_order_snapshots_ticket", "mt5_order_snapshots", ["ticket"])
    op.create_index("ix_mt5_order_snapshots_symbol", "mt5_order_snapshots", ["symbol"])

    op.create_table(
        "mt5_connection_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("server", sa.String(128)),
        sa.Column("login_masked", sa.String(32)),
        sa.Column("reasons", sa.Text),
        sa.Column("event_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_connection_events_timestamp", "mt5_connection_events", ["timestamp"])

    op.create_table(
        "mt5_data_quality_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reasons", sa.Text),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("report_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_mt5_data_quality_events_timestamp", "mt5_data_quality_events", ["timestamp"])
    op.create_index("ix_mt5_data_quality_events_symbol", "mt5_data_quality_events", ["symbol"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
