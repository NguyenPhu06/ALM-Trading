"""Phase 15 AI research lab: strategies, experiments, findings.

Revision ID: 20260829_0018; Revises: 20260828_0017

Declarations and measurements only. A `research_strategies` row describes rules;
it is not an executable object and nothing reads it to trade. `fingerprint` is a
content hash of the declaration, so two identical strategies under different
names are detectable rather than double-counted as two hypotheses.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260829_0018"
down_revision = "20260828_0017"
branch_labels = None
depends_on = None

TABLES = ("research_findings", "research_experiments", "research_strategies")


def upgrade() -> None:
    op.create_table(
        "research_strategies",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("strategy_id", sa.String(64), nullable=False, index=True),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("fingerprint", sa.String(32), nullable=False, index=True),
        sa.Column("features", sa.Text),
        sa.Column("timeframes", sa.String(255)),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("record_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "research_experiments",
        sa.Column("experiment_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("strategy_key", sa.String(128), index=True),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64)),
        sa.Column("dataset_version", sa.String(128), index=True),
        sa.Column("label_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("sample_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expectancy", sa.Float),
        sa.Column("win_rate", sa.Float),
        sa.Column("net_pnl", sa.Float),
        sa.Column("profit_factor", sa.Float),
        sa.Column("maximum_drawdown", sa.Float),
        sa.Column("sharpe_like", sa.Float),
        sa.Column("reliable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.String(32), nullable=False,
                  server_default="FORWARD_OBSERVATION"),
        sa.Column("used_holdout", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("spec_json", sa.JSON, nullable=False),
        sa.Column("metrics_json", sa.JSON, nullable=False),
    )
    op.create_table(
        "research_findings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("study", sa.String(64), nullable=False, index=True),
        sa.Column("subject", sa.String(128), nullable=False, index=True),
        sa.Column("verdict", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("sample_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("effect_size", sa.Float),
        sa.Column("significant", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("experiment_id", sa.String(64), index=True),
        sa.Column("reasons", sa.Text),
        sa.Column("finding_json", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
