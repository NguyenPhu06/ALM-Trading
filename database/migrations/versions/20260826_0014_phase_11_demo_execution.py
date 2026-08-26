"""Phase 11 DEMO execution audit store.

Revision ID: 20260826_0014; Revises: 20260826_0013

No credential is persisted: there is no password, token or secret column here.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260826_0014"
down_revision = "20260826_0013"
branch_labels = None
depends_on = None

TABLES = (
    "kill_switch_events", "reconciliation_records", "execution_audit_logs",
    "execution_results", "execution_requests",
)


def upgrade() -> None:
    op.create_table(
        "execution_requests",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("price", sa.Float),
        sa.Column("sl", sa.Float),
        sa.Column("tp", sa.Float),
        sa.Column("intent", sa.String(16), nullable=False),
        sa.Column("strategy_id", sa.String(64)),
        sa.Column("signal_id", sa.String(64)),
        sa.Column("comment", sa.String(255)),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("request_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_execution_requests_timestamp", "execution_requests", ["timestamp"])
    op.create_index("ix_execution_requests_symbol", "execution_requests", ["symbol"])

    op.create_table(
        "execution_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("broker_ticket", sa.BigInteger),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("requested_volume", sa.Float, nullable=False),
        sa.Column("filled_volume", sa.Float, nullable=False, server_default="0"),
        sa.Column("requested_price", sa.Float),
        sa.Column("filled_price", sa.Float),
        sa.Column("sl", sa.Float),
        sa.Column("tp", sa.Float),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("result_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_execution_results_request_id", "execution_results", ["request_id"])
    op.create_index("ix_execution_results_timestamp", "execution_results", ["timestamp"])
    op.create_index("ix_execution_results_status", "execution_results", ["status"])

    op.create_table(
        "execution_audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("approved", sa.Boolean),
        sa.Column("reasons", sa.Text),
        sa.Column("actor", sa.String(64), nullable=False, server_default="system"),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_execution_audit_logs_request_id", "execution_audit_logs", ["request_id"])
    op.create_index("ix_execution_audit_logs_timestamp", "execution_audit_logs", ["timestamp"])
    op.create_index("ix_execution_audit_logs_stage", "execution_audit_logs", ["stage"])

    op.create_table(
        "reconciliation_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("broker_ticket", sa.BigInteger),
        sa.Column("symbol", sa.String(32)),
        sa.Column("reasons", sa.Text),
        sa.Column("record_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_reconciliation_records_request_id", "reconciliation_records", ["request_id"])
    op.create_index("ix_reconciliation_records_timestamp", "reconciliation_records", ["timestamp"])
    op.create_index("ix_reconciliation_records_status", "reconciliation_records", ["status"])

    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("engaged", sa.Boolean, nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False, server_default="system"),
        sa.Column("event_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_kill_switch_events_timestamp", "kill_switch_events", ["timestamp"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
