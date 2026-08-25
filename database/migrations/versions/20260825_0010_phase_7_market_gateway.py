"""Phase 7 real market gateway audit tables.

Revision ID: 20260825_0010
Revises: 20260824_0009
"""
from alembic import op
import sqlalchemy as sa
revision="20260825_0010";down_revision="20260824_0009";branch_labels=None;depends_on=None

def audit_columns():return [sa.Column("source",sa.String(64),nullable=False),sa.Column("ingestion_timestamp",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now())]
def upgrade():
    op.create_table("market_quotes",sa.Column("id",sa.Integer,primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("symbol",sa.String(32),nullable=False),sa.Column("bid",sa.Float),sa.Column("ask",sa.Float),sa.Column("spread",sa.Float),sa.Column("spread_percent",sa.Float),sa.Column("mid_price",sa.Float),sa.Column("bid_volume",sa.Float),sa.Column("ask_volume",sa.Float),sa.Column("tick_volume",sa.Float),*audit_columns());op.create_index("ix_market_quotes_timestamp","market_quotes",["timestamp"]);op.create_index("ix_market_quotes_symbol","market_quotes",["symbol"])
    op.create_table("market_sessions",sa.Column("id",sa.Integer,primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("symbol",sa.String(32),nullable=False),sa.Column("session",sa.String(64),nullable=False),*audit_columns())
    op.create_table("data_quality_reports",sa.Column("id",sa.Integer,primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("symbol",sa.String(32),nullable=False),sa.Column("timeframe",sa.String(8),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("report_json",sa.JSON,nullable=False),*audit_columns())
    op.create_table("provider_status",sa.Column("id",sa.Integer,primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("provider",sa.String(64),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("metadata_json",sa.JSON,nullable=False),*audit_columns())
    op.create_table("institutional_observations",sa.Column("id",sa.Integer,primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("asset",sa.String(32),nullable=False),sa.Column("provider_status",sa.String(32),nullable=False),sa.Column("pressure_proxy",sa.Float),sa.Column("confidence",sa.Float,nullable=False),sa.Column("is_proxy",sa.Boolean,nullable=False),*audit_columns())
    op.create_table("market_datasets",sa.Column("dataset_id",sa.String(128),primary_key=True),sa.Column("source",sa.String(64),nullable=False),sa.Column("symbol",sa.String(32),nullable=False),sa.Column("timeframe",sa.String(8),nullable=False),sa.Column("start_time",sa.DateTime(timezone=True),nullable=False),sa.Column("end_time",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("metadata_json",sa.JSON,nullable=False))
    op.create_table("economic_calendar_events",sa.Column("id",sa.Integer,primary_key=True),sa.Column("event",sa.String(255),nullable=False),sa.Column("currency",sa.String(8),nullable=False),sa.Column("importance",sa.String(16),nullable=False),sa.Column("scheduled_time",sa.DateTime(timezone=True),nullable=False),sa.Column("actual",sa.Float),sa.Column("forecast",sa.Float),sa.Column("previous",sa.Float),*audit_columns())
def downgrade():
    for table in ("economic_calendar_events","market_datasets","institutional_observations","provider_status","data_quality_reports","market_sessions","market_quotes"):op.drop_table(table)
