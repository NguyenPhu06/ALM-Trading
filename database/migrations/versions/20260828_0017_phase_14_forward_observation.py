"""Phase 14 forward observation loop: observations, outcomes, errors, performance, edge, runs.

Revision ID: 20260828_0017; Revises: 20260827_0016

Records of what the 24/7 loop observed. No table here holds an order, a broker
ticket, a credential or a model binary. `observations.cycle_id` is unique: the
deterministic cycle identity is what makes a restart idempotent (section 27).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260828_0017"
down_revision = "20260827_0016"
branch_labels = None
depends_on = None

TABLES = ("training_runs", "edge_evaluations", "model_performance", "model_errors",
          "observation_outcomes", "observations")


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column("cycle_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("entry_price", sa.Float),
        sa.Column("direction", sa.String(16), nullable=False, server_default="WAIT"),
        sa.Column("strategy", sa.String(32)),
        sa.Column("market_regime", sa.String(24)),
        sa.Column("session", sa.String(32)),
        sa.Column("feature_version", sa.String(64)),
        sa.Column("model_version", sa.String(64)),
        sa.Column("nn_confidence", sa.Float),
        sa.Column("risk_state", sa.String(16)),
        sa.Column("observation_horizon", sa.String(16), nullable=False, server_default="1h"),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("deadline", sa.DateTime(timezone=True), index=True),
        sa.Column("failure_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "observation_outcomes",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("future_price", sa.Float, nullable=False),
        sa.Column("future_return", sa.Float, nullable=False),
        sa.Column("mfe", sa.Float),
        sa.Column("mae", sa.Float),
        sa.Column("hypothetical_pnl", sa.Float),
        sa.Column("net_hypothetical_pnl", sa.Float, nullable=False),
        sa.Column("estimated_cost", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("holding_time", sa.Float),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("regime", sa.String(24)),
        sa.Column("session", sa.String(32)),
        sa.Column("timeframe", sa.String(16)),
        sa.Column("label_version", sa.String(64)),
        sa.Column("evidence", sa.String(32), nullable=False,
                  server_default="FORWARD_OBSERVATION"),
        sa.Column("outcome_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "model_errors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("observation_id", sa.String(64), nullable=False, index=True),
        sa.Column("model_id", sa.String(64), index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("predicted", sa.String(16), nullable=False),
        sa.Column("actual", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("error_class", sa.String(32), nullable=False, index=True),
        sa.Column("tags", sa.String(255)),
        sa.Column("high_confidence_failure", sa.Boolean, nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("net_pnl", sa.Float),
        sa.Column("regime", sa.String(24)),
        sa.Column("session", sa.String(32)),
        sa.Column("error_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "model_performance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(64), index=True),
        sa.Column("model_version", sa.String(64)),
        sa.Column("window", sa.String(16), nullable=False, index=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("samples", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reliable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("win_rate", sa.Float),
        sa.Column("expectancy", sa.Float),
        sa.Column("profit_factor", sa.Float),
        sa.Column("net_pnl", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("average_mae", sa.Float),
        sa.Column("average_mfe", sa.Float),
        sa.Column("prediction_accuracy", sa.Float),
        sa.Column("brier_score", sa.Float),
        sa.Column("evidence", sa.String(32), nullable=False,
                  server_default="FORWARD_OBSERVATION"),
        sa.Column("metrics_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "edge_evaluations",
        sa.Column("evaluation_id", sa.String(64), primary_key=True),
        sa.Column("model_id", sa.String(64), index=True),
        sa.Column("symbol", sa.String(32), index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("verdict", sa.String(24), nullable=False, index=True),
        sa.Column("samples", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expectancy", sa.Float),
        sa.Column("win_rate", sa.Float),
        sa.Column("profit_factor", sa.Float),
        sa.Column("net_pnl", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("beats_baselines", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reasons", sa.Text),
        sa.Column("evidence", sa.String(32), nullable=False,
                  server_default="FORWARD_OBSERVATION"),
        sa.Column("report_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "training_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("model_id", sa.String(64), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("dataset_id", sa.String(128), index=True),
        sa.Column("trigger", sa.String(32)),
        sa.Column("requested_by", sa.String(128)),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("failed_step", sa.String(24)),
        sa.Column("state", sa.String(16)),
        sa.Column("edge_verdict", sa.String(24)),
        sa.Column("registered", sa.Boolean, nullable=False, server_default=sa.false()),
        # A training run never promotes; the column exists so the record can say so.
        sa.Column("promoted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text),
        sa.Column("run_json", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
