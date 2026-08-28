"""Phase 17 shadow trading and DEMO validation.

Revision ID: 20260831_0020; Revises: 20260830_0019

Seven tables. Two of them carry a column that is always false or zero, on
purpose: `shadow_signals.orders_sent` and `circuit_breaker_events.positions_closed`
make the invariants visible in the data rather than only in prose — a shadow
signal has no transport, and tripping the breaker blocks new orders without
liquidating anything.

Revision 20260824_0001 runs `Base.metadata.create_all(checkfirst=True)`, so on a
database built from scratch these tables already exist by the time this revision
runs. Skipping what is present keeps both paths working.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260831_0020"
down_revision = "20260830_0019"
branch_labels = None
depends_on = None

TABLES = ("circuit_breaker_events", "performance_gates", "validation_runs",
          "execution_quality", "demo_comparisons", "shadow_outcomes", "shadow_signals")


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _skipping(present: set[str]):
    def create(name: str, *columns) -> None:
        if name in present:
            return
        op.create_table(name, *columns)

    return create


def upgrade() -> None:
    create = _skipping(_existing())

    create(
        "shadow_signals",
        sa.Column("shadow_signal_id", sa.String(64), primary_key=True),
        sa.Column("demo_execution_request_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("entry", sa.Float),
        sa.Column("stop_loss", sa.Float),
        sa.Column("take_profit", sa.Float),
        sa.Column("volume", sa.Float, nullable=False, server_default="0"),
        sa.Column("strategy", sa.String(64)),
        sa.Column("strategy_version", sa.String(64)),
        sa.Column("model_version", sa.String(64)),
        sa.Column("feature_version", sa.String(64)),
        sa.Column("confidence", sa.Float),
        sa.Column("risk_snapshot_id", sa.String(64)),
        sa.Column("risk_state", sa.String(16)),
        sa.Column("session", sa.String(32), index=True),
        sa.Column("regime", sa.String(32), index=True),
        sa.Column("timeframe", sa.String(8)),
        sa.Column("signal_timeframe", sa.String(8)),
        sa.Column("spread", sa.Float),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("decision_approved", sa.Boolean, nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("executed", sa.Boolean, nullable=False, server_default=sa.false(), index=True),
        sa.Column("not_executed_reason", sa.String(64)),
        sa.Column("blocked_reasons", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN", index=True),
        sa.Column("orders_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("signal_json", sa.JSON, nullable=False),
    )
    create(
        "shadow_outcomes",
        sa.Column("shadow_signal_id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("expected_entry", sa.Float, nullable=False),
        sa.Column("expected_exit", sa.Float, nullable=False),
        sa.Column("expected_pnl", sa.Float, nullable=False),
        sa.Column("mfe", sa.Float, nullable=False, server_default="0"),
        sa.Column("mae", sa.Float, nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("spread", sa.Float, nullable=False, server_default="0"),
        sa.Column("slippage_estimate", sa.Float, nullable=False, server_default="0"),
        sa.Column("commission_estimate", sa.Float, nullable=False, server_default="0"),
        sa.Column("net_expected_pnl", sa.Float, nullable=False),
        sa.Column("exit_reason", sa.String(48)),
        sa.Column("executed", sa.Boolean, nullable=False, server_default=sa.false(), index=True),
        sa.Column("session", sa.String(32), index=True),
        sa.Column("regime", sa.String(32), index=True),
        sa.Column("outcome_json", sa.JSON, nullable=False),
    )
    create(
        "demo_comparisons",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("shadow_signal_id", sa.String(64), nullable=False, index=True),
        sa.Column("demo_execution_request_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("signal_difference", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("entry_difference", sa.Float),
        sa.Column("exit_difference", sa.Float),
        sa.Column("slippage_difference", sa.Float),
        sa.Column("cost_difference", sa.Float),
        sa.Column("pnl_difference", sa.Float),
        sa.Column("mae_difference", sa.Float),
        sa.Column("mfe_difference", sa.Float),
        sa.Column("time_difference", sa.Float),
        sa.Column("primary_kind", sa.String(32), nullable=False, index=True),
        sa.Column("kinds", sa.Text),
        sa.Column("matched", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("shadow_net_pnl", sa.Float),
        sa.Column("demo_net_pnl", sa.Float),
        sa.Column("comparison_json", sa.JSON, nullable=False),
    )
    create(
        "execution_quality",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window", sa.String(16), nullable=False, index=True),
        sa.Column("submitted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errored", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fill_rate", sa.Float),
        sa.Column("rejection_rate", sa.Float),
        sa.Column("average_slippage", sa.Float),
        sa.Column("worst_slippage", sa.Float),
        sa.Column("reconciliation_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("connection_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reliable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("quality_json", sa.JSON, nullable=False),
    )
    create(
        "validation_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("window", sa.String(16)),
        sa.Column("samples", sa.Integer, nullable=False, server_default="0"),
        sa.Column("edge_status", sa.String(24), nullable=False,
                  server_default="INSUFFICIENT_DATA"),
        sa.Column("passed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reasons", sa.Text),
        sa.Column("report_json", sa.JSON, nullable=False),
    )
    create(
        "performance_gates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), index=True),
        sa.Column("gate", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("observed", sa.Float),
        sa.Column("threshold", sa.Float),
        sa.Column("detail", sa.Text),
        sa.Column("enabled_execution", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("gate_json", sa.JSON, nullable=False),
    )
    create(
        "circuit_breaker_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("state", sa.String(16), nullable=False, index=True),
        sa.Column("triggers", sa.Text),
        sa.Column("reasons", sa.Text),
        sa.Column("actor", sa.String(128), nullable=False, server_default="system"),
        sa.Column("positions_closed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("health_check", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("risk_check", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("account_validation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("human_approval", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("event_json", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    present = _existing()
    for table in TABLES:
        if table in present:
            op.drop_table(table)
