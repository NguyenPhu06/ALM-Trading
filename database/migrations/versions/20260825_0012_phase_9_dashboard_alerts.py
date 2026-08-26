"""Phase 9 dashboard alert history. Revision ID: 20260825_0012; Revises: 20260825_0011"""
from alembic import op
import sqlalchemy as sa
revision="20260825_0012";down_revision="20260825_0011";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("dashboard_alerts",sa.Column("alert_id",sa.String(64),primary_key=True),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("symbol",sa.String(32)),sa.Column("alert_type",sa.String(64),nullable=False),sa.Column("severity",sa.String(16),nullable=False),sa.Column("title",sa.String(255),nullable=False),sa.Column("message",sa.Text,nullable=False),sa.Column("source",sa.String(64),nullable=False),sa.Column("version",sa.String(64),nullable=False),sa.Column("data_quality",sa.String(16),nullable=False),sa.Column("read",sa.Boolean,nullable=False,server_default=sa.false()),sa.Column("context_json",sa.JSON));op.create_index("ix_dashboard_alerts_timestamp","dashboard_alerts",["timestamp"])
def downgrade():op.drop_table("dashboard_alerts")
