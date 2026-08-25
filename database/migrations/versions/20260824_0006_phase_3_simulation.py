"""Phase 3 backtest-only simulated trade audit.

Revision ID: 20260824_0006
Revises: 20260824_0005
"""
from alembic import op
import sqlalchemy as sa


revision = "20260824_0006"
down_revision = "20260824_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("simulated_trades"):
        return
    op.create_table(
        "simulated_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("counter_trend_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("entries_json", sa.JSON(), nullable=False),
        sa.Column("evaluations_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_simulated_trades_entry_time", "simulated_trades", ["entry_time"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("simulated_trades"):
        op.drop_table("simulated_trades")
