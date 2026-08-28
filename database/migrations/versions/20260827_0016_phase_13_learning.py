"""Phase 13 learning pipeline: dataset audits, model registry, drift, retraining.

Revision ID: 20260827_0016; Revises: 20260827_0015

Metadata only. Model artifacts live on disk under phase_13.artifacts_path and are
gitignored. No table here stores a binary or a credential.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0016"
down_revision = "20260827_0015"
branch_labels = None
depends_on = None

TABLES = ("retraining_requests", "model_drift_events", "model_registry", "dataset_audits")

# Section 31 additions to the Phase 12 observation_performance table.
OBSERVATION_COLUMNS = (
    ("observation_id", sa.String(64)),
    ("future_price", sa.Float),
    ("future_return", sa.Float),
    ("nn_probability", sa.Float),
    ("strategy_decision", sa.String(24)),
    ("horizon", sa.String(16)),
    ("label_version", sa.String(64)),
)


def upgrade() -> None:
    op.create_table(
        "dataset_audits",
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("label_version", sa.String(64), nullable=False),
        sa.Column("preprocessing_version", sa.String(64), nullable=False),
        sa.Column("horizon", sa.String(16)),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("symbols", sa.String(255), nullable=False),
        sa.Column("timeframes", sa.String(255), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("missing_values", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("class_distribution", sa.JSON, nullable=False),
        sa.Column("audit_json", sa.JSON, nullable=False),
    )
    op.create_index("ix_dataset_audits_created_at", "dataset_audits", ["created_at"])
    op.create_index("ix_dataset_audits_feature_version", "dataset_audits", ["feature_version"])

    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("task_key", sa.String(128), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("label_version", sa.String(64), nullable=False),
        sa.Column("training_dataset_version", sa.String(128), nullable=False),
        sa.Column("preprocessing_version", sa.String(64), nullable=False),
        sa.Column("training_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edge_verdict", sa.String(24), nullable=False, server_default="NO_EDGE"),
        sa.Column("artifact_path", sa.String(512)),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("record_json", sa.JSON, nullable=False),
    )
    for column in ("model_version", "task_key", "symbol", "state", "training_timestamp"):
        op.create_index(f"ix_model_registry_{column}", "model_registry", [column])

    op.create_table(
        "model_drift_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(64)),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("metric", sa.Float, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("flagged", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("action", sa.String(24), nullable=False, server_default="FLAG_ONLY"),
        sa.Column("detail", sa.Text),
        sa.Column("event_json", sa.JSON, nullable=False),
    )
    for column in ("timestamp", "model_id", "kind"):
        op.create_index(f"ix_model_drift_events_{column}", "model_drift_events", [column])

    op.create_table(
        "retraining_requests",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("triggers", sa.String(255), nullable=False),
        sa.Column("reasons", sa.Text),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("model_id", sa.String(64)),
        sa.Column("request_json", sa.JSON, nullable=False),
    )
    for column in ("created_at", "state", "model_id"):
        op.create_index(f"ix_retraining_requests_{column}", "retraining_requests", [column])

    for name, column_type in OBSERVATION_COLUMNS:
        op.add_column("observation_performance", sa.Column(name, column_type))
    op.create_index("ix_observation_performance_observation_id",
                    "observation_performance", ["observation_id"])


def downgrade() -> None:
    op.drop_index("ix_observation_performance_observation_id", "observation_performance")
    for name, _ in OBSERVATION_COLUMNS:
        op.drop_column("observation_performance", name)
    for table in TABLES:
        op.drop_table(table)
