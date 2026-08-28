"""Phase 16 controlled DEMO trading: proposals, journal, daily risk, monitoring.

Revision ID: 20260830_0019; Revises: 20260829_0018

Six tables, all DEMO-only and all audit-shaped. `demo_execution_proposals` is
the manual-approval record: it names the human who approved and the reason, so a
DEMO fill can always be traced back to a person or to automation.

`demo_emergency_events.positions_closed` exists as a column that is always false.
It is there so the invariant is visible in the data rather than only in prose: an
emergency engages the kill switch and blocks new orders; it never liquidates.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260830_0019"
down_revision = "20260829_0018"
branch_labels = None
depends_on = None

TABLES = ("demo_emergency_events", "demo_paper_comparisons", "demo_position_snapshots",
          "demo_daily_risk", "demo_trade_journal", "demo_execution_proposals")


def _existing() -> set[str]:
    """Which of these tables the database already has.

    Revision 20260824_0001 runs `Base.metadata.create_all(checkfirst=True)`, so on
    a database built from scratch every declared table — including these six —
    already exists by the time this revision runs. Skipping what is present keeps
    both paths working: a fresh build and an upgrade from 20260829_0018.
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    present = _existing()
    create = _skipping(present)

    create(
        "demo_execution_proposals",
        sa.Column("proposal_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, index=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_reason", sa.String(255)),
        sa.Column("rejected_reason", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("blocked_by", sa.Text),
        sa.Column("proposal_json", sa.JSON, nullable=False),
    )
    create(
        "demo_trade_journal",
        sa.Column("trade_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("broker_ticket", sa.BigInteger),
        sa.Column("exit_reason", sa.String(48), index=True),
        sa.Column("pnl", sa.Float),
        sa.Column("gross_pnl", sa.Float),
        sa.Column("mae", sa.Float),
        sa.Column("mfe", sa.Float),
        sa.Column("commission", sa.Float, nullable=False, server_default="0"),
        sa.Column("swap", sa.Float, nullable=False, server_default="0"),
        sa.Column("slippage", sa.Float),
        sa.Column("session", sa.String(32)),
        sa.Column("regime", sa.String(32)),
        sa.Column("model_version", sa.String(64)),
        sa.Column("strategy_version", sa.String(64)),
        sa.Column("feature_version", sa.String(64)),
        sa.Column("closed", sa.Boolean, nullable=False, server_default=sa.false(), index=True),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("journal_json", sa.JSON, nullable=False),
    )
    create(
        "demo_daily_risk",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trading_day", sa.Date, nullable=False, index=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("starting_equity", sa.Float, nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("peak_equity", sa.Float, nullable=False),
        sa.Column("daily_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_drawdown", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_drawdown", sa.Float, nullable=False, server_default="0"),
        sa.Column("trade_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reasons", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_json", sa.JSON, nullable=False),
        sa.UniqueConstraint("trading_day", "timezone", name="uq_demo_daily_risk_day"),
    )
    create(
        "demo_position_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticket", sa.BigInteger, nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("current_price", sa.Float, nullable=False),
        sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("mae", sa.Float, nullable=False, server_default="0"),
        sa.Column("mfe", sa.Float, nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("dca_levels", sa.Integer, nullable=False, server_default="0"),
        sa.Column("snapshot_json", sa.JSON, nullable=False),
    )
    create(
        "demo_paper_comparisons",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("paper_entry", sa.Float),
        sa.Column("demo_entry", sa.Float),
        sa.Column("paper_exit", sa.Float),
        sa.Column("demo_exit", sa.Float),
        sa.Column("entry_difference", sa.Float),
        sa.Column("exit_difference", sa.Float),
        sa.Column("spread", sa.Float),
        sa.Column("slippage", sa.Float),
        sa.Column("commission", sa.Float),
        sa.Column("swap", sa.Float),
        sa.Column("pnl_difference", sa.Float),
        sa.Column("within_tolerance", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("errors", sa.Text),
        sa.Column("comparison_json", sa.JSON, nullable=False),
    )
    create(
        "demo_emergency_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("triggers", sa.Text, nullable=False),
        sa.Column("action", sa.String(48)),
        sa.Column("shutdown", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("positions_closed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("event_json", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    present = _existing()
    for table in TABLES:
        if table in present:
            op.drop_table(table)


def _skipping(present: set[str]):
    def create(name: str, *columns) -> None:
        if name in present:
            return
        op.create_table(name, *columns)

    return create
