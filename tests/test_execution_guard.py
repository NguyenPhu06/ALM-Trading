"""ExecutionGuard is the only authority that may approve an order."""
import pytest

from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.execution_guard import ExecutionGuard, GuardContext
from execution.mt5.order_request import ExecutionIntent
from execution.mt5.order_result import ExecutionRejected, RejectionReason
from tests.phase11_helpers import DEMO_SERVER, armed, context, guard_for, order, settings


def account(**overrides):
    base = dict(login=1, server=DEMO_SERVER, broker="Exness", currency="USD", balance=1000.0,
                equity=1000.0, margin=0.0, free_margin=1000.0, margin_level=0.0,
                trade_mode=TradeMode.DEMO)
    base.update(overrides)
    return MT5Account(**base)


def test_a_fully_valid_demo_request_is_approved():
    decision = guard_for().evaluate(order(), context())
    assert decision.approved, decision.reasons
    assert decision.reasons == () and all(decision.checks.values())


def test_the_default_configuration_approves_nothing():
    """Every gate ships closed, so an unconfigured system cannot trade."""
    decision = ExecutionGuard(settings(), kill_switch=guard_for().kill_switch).evaluate(order(), context())
    assert not decision.approved
    assert RejectionReason.DEMO_TRADING_DISABLED in decision.reasons
    assert RejectionReason.MT5_EXECUTION_DISABLED in decision.reasons


def test_every_check_group_is_evaluated_and_reported():
    decision = guard_for().evaluate(order(), context())
    assert set(decision.checks) == {
        "environment", "kill_switch", "connection", "account", "symbol", "volume",
        "price", "spread", "stops", "risk", "session", "strategy",
    }


# ------------------------------------------------------------------ environment
def test_a_non_demo_environment_is_refused():
    config = armed()
    object.__setattr__(config, "trading_environment", "LIVE")
    decision = ExecutionGuard(config, kill_switch=guard_for().kill_switch).evaluate(order(), context())
    assert RejectionReason.ENVIRONMENT_NOT_DEMO in decision.reasons


def test_live_trading_enabled_is_refused_even_if_everything_else_is_open():
    config = armed()
    object.__setattr__(config, "live_trading_enabled", True)
    decision = ExecutionGuard(config, kill_switch=guard_for().kill_switch).evaluate(order(), context())
    assert not decision.approved and RejectionReason.LIVE_TRADING_ENABLED in decision.reasons


def test_read_only_mode_refuses_execution():
    """Settings refuses demo_trading_enabled together with mt5_read_only, so the
    guard is tested with the legal read-only posture instead."""
    config = settings(mt5_read_only=True, mt5_execution_enabled=True, execution_kill_switch=False)
    decision = guard_for(config, engaged=False).evaluate(order(), context())
    assert not decision.approved and RejectionReason.MT5_READ_ONLY in decision.reasons


def test_settings_refuse_a_contradictory_read_only_execution_config():
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError, match="MT5_READ_ONLY must be false"):
        settings(demo_trading_enabled=True, mt5_read_only=True)


# ---------------------------------------------------------------------- account
def test_a_real_account_is_refused():
    decision = guard_for().evaluate(order(), context(account=account(trade_mode=TradeMode.REAL)))
    assert not decision.approved and RejectionReason.ACCOUNT_IS_REAL in decision.reasons


def test_a_missing_account_is_refused():
    decision = guard_for().evaluate(order(), context(account=None))
    assert RejectionReason.ACCOUNT_UNAVAILABLE in decision.reasons


@pytest.mark.parametrize("server", ["Exness-Real12", "LiveServer", "", None])
def test_a_non_demo_server_is_refused(server):
    decision = guard_for().evaluate(order(), context(account=account(server=server)))
    assert RejectionReason.SERVER_NOT_DEMO in decision.reasons


@pytest.mark.parametrize("server", ["Exness-MT5Trial8", "Broker-Demo-3", "practice-1", "TestNet"])
def test_recognised_demo_servers_pass(server):
    decision = guard_for().evaluate(order(), context(account=account(server=server)))
    assert RejectionReason.SERVER_NOT_DEMO not in decision.reasons


def test_a_disconnected_terminal_is_refused():
    decision = guard_for().evaluate(order(), context(connected=False))
    assert RejectionReason.NOT_CONNECTED in decision.reasons


# ------------------------------------------------------------------------ risk
def test_a_blocked_risk_state_is_refused():
    decision = guard_for().evaluate(order(), context(risk_allowed=False))
    assert RejectionReason.RISK_BLOCKED in decision.reasons


def test_daily_drawdown_beyond_the_limit_is_refused():
    decision = guard_for().evaluate(order(), context(daily_drawdown=0.05))
    assert RejectionReason.DAILY_DRAWDOWN_EXCEEDED in decision.reasons


def test_exposure_beyond_the_limit_is_refused():
    decision = guard_for().evaluate(order(), context(exposure=999_999))
    assert RejectionReason.MAXIMUM_EXPOSURE in decision.reasons


def test_the_position_limit_is_enforced_for_a_new_entry():
    decision = guard_for().evaluate(order(intent=ExecutionIntent.NEW_ENTRY),
                                    context(open_positions=3, strategy_status="EXECUTABLE_SIMULATION"))
    assert RejectionReason.POSITION_LIMIT in decision.reasons


def test_the_dca_limit_is_enforced_for_a_dca_request():
    decision = guard_for().evaluate(order(intent=ExecutionIntent.DCA),
                                    context(dca_entries=3, strategy_status="EXECUTABLE_SIMULATION"))
    assert RejectionReason.DCA_LIMIT in decision.reasons


def test_a_dca_request_is_not_refused_by_the_position_limit():
    """DCA adds to an existing position, so it is counted against the DCA limit."""
    decision = guard_for().evaluate(order(intent=ExecutionIntent.DCA),
                                    context(open_positions=3, dca_entries=0))
    assert RejectionReason.POSITION_LIMIT not in decision.reasons


# --------------------------------------------------------------------- market
def test_an_extreme_spread_is_refused():
    decision = guard_for().evaluate(order(), context(quote={"bid": 1.1000, "ask": 1.1100}))
    assert RejectionReason.SPREAD_TOO_WIDE in decision.reasons


def test_a_missing_quote_is_refused():
    decision = guard_for().evaluate(order(), context(quote=None))
    assert RejectionReason.QUOTE_UNAVAILABLE in decision.reasons


def test_a_session_outside_the_allowlist_is_refused():
    decision = guard_for().evaluate(order(), context(session="OFF_SESSION"))
    assert RejectionReason.SESSION_NOT_ALLOWED in decision.reasons


# -------------------------------------------------------------------- strategy
def test_a_strategy_order_without_an_executable_setup_is_refused():
    decision = guard_for().evaluate(order(intent=ExecutionIntent.NEW_ENTRY),
                                    context(strategy_status="WATCH"))
    assert RejectionReason.STRATEGY_NOT_EXECUTABLE in decision.reasons


def test_a_manual_test_needs_no_strategy_status():
    decision = guard_for().evaluate(order(intent=ExecutionIntent.MANUAL_TEST),
                                    context(strategy_status=None))
    assert RejectionReason.STRATEGY_NOT_EXECUTABLE not in decision.reasons


# ------------------------------------------------------------------ assertion
def test_assert_allowed_raises_with_every_reason():
    with pytest.raises(ExecutionRejected) as error:
        guard_for().assert_allowed(order(volume=99), context(account=None))
    assert RejectionReason.ACCOUNT_UNAVAILABLE in error.value.reasons
    assert RejectionReason.VOLUME_ABOVE_LIMIT in error.value.reasons


def test_multiple_failures_are_all_reported_not_just_the_first():
    decision = guard_for().evaluate(order(volume=99, symbol="ZZZZZZ"),
                                    context(connected=False, risk_allowed=False))
    assert {RejectionReason.VOLUME_ABOVE_LIMIT, RejectionReason.INVALID_SYMBOL,
            RejectionReason.NOT_CONNECTED, RejectionReason.RISK_BLOCKED} <= set(decision.reasons)
