"""Phase 4 historical ML dataset metadata and versioned feature/label rows.

Revision ID: 20260824_0007
Revises: 20260824_0006
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0007"
down_revision = "20260824_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_features"):
        op.create_table(
            "market_features",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("base_timeframe", sa.String(8), nullable=False, server_default="M15"),
            sa.Column("feature_version", sa.String(64), nullable=False),
            sa.Column("features_json", sa.JSON(), nullable=False),
            sa.Column("schema_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("symbol", "base_timeframe", "timestamp", "feature_version", name="uq_market_feature_version"),
        )
        op.create_index("ix_market_features_symbol_timestamp", "market_features", ["symbol", "timestamp"])
    if not inspector.has_table("market_labels"):
        op.create_table(
            "market_labels",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("label_end_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("base_timeframe", sa.String(8), nullable=False, server_default="M15"),
            sa.Column("label_version", sa.String(64), nullable=False),
            sa.Column("labels_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("symbol", "base_timeframe", "timestamp", "label_version", name="uq_market_label_version"),
        )
        op.create_index("ix_market_labels_symbol_timestamp", "market_labels", ["symbol", "timestamp"])
    if not inspector.has_table("dataset_metadata"):
        op.create_table(
            "dataset_metadata",
            sa.Column("dataset_id", sa.String(128), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("timeframes_json", sa.JSON(), nullable=False),
            sa.Column("feature_version", sa.String(64), nullable=False),
            sa.Column("label_version", sa.String(64), nullable=False),
            sa.Column("data_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("data_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("schema_hash", sa.String(64), nullable=False),
            sa.Column("dataset_hash", sa.String(64), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
        )
        op.create_index("ix_dataset_metadata_symbol_created", "dataset_metadata", ["symbol", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("dataset_metadata", "market_labels", "market_features"):
        if inspector.has_table(table):
            op.drop_table(table)
