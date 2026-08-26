"""Position lifecycle and persistence.

Phase 8 constructed a PositionStateMachine and then assigned `position.state`
directly, so none of its rules were enforced; TimeExitEngine was never connected
to the paper service; close_position persisted `journals[-1]` instead of the
journal it had just closed; and paper state lived only in process memory.
"""
import pytest

from database.models import PaperPositionRecord, PaperTradeJournalRecord
from database.repositories import PaperTradingRepository
from paper import (
    Direction,
    InvalidPositionTransition,
    OrderType,
    PaperOrderRequest,
    PaperTradingService,
    PositionState,
    PositionStateMachine,
)
from paper.service import bound_repository
from strategy import ExitAction, TimeExitEngine, TradingSessionEngine
from tests.phase7_helpers import NOW
from tests.phase8_helpers import PRED, QUOTE, RISK_OK, request, running_service


def open_position(service=None):
    service = service or running_service()
    entry = service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                          risk_decision=RISK_OK, data_quality="VALID",
                          provider_status="ONLINE", prediction=PRED)
    assert entry.accepted
    return service, entry.order.position_id


# ---------------------------------------------------------------- state machine
def test_entry_walks_the_state_machine_to_open():
    service, position_id = open_position()
    assert service.positions[position_id].state is PositionState.OPEN


def test_transition_refuses_an_illegal_jump():
    service, position_id = open_position()
    with pytest.raises(InvalidPositionTransition):
        service.transition(service.positions[position_id], PositionState.CLOSED)


def test_dca_moves_through_dca_allowed_and_back_to_open():
    service, position_id = open_position()
    result = service.dca(position_id, request(OrderType.DCA, position_id=position_id), quote=QUOTE,
                         market_regime="TRENDING", structure_state="VALID", risk_state="ALLOWED",
                         data_quality="VALID", provider_status="ONLINE", prediction=PRED)
    assert result.accepted
    assert service.positions[position_id].state is PositionState.OPEN
    assert service.positions[position_id].dca_entries == 1


def test_a_blocked_dca_records_dca_blocked_and_leaves_the_position_open():
    service, position_id = open_position()
    result = service.dca(position_id, request(OrderType.DCA, position_id=position_id), quote=QUOTE,
                         market_regime="TRENDING", structure_state="VALID", risk_state="ALLOWED",
                         data_quality="INVALID", provider_status="ONLINE", prediction=PRED)
    assert not result.accepted
    assert service.positions[position_id].state is PositionState.OPEN


def test_close_walks_through_exit_pending(monkeypatch):
    service, position_id = open_position()
    seen = []
    original = PositionStateMachine.transition
    monkeypatch.setattr(PositionStateMachine, "transition",
                        lambda self, current, target: seen.append(target) or original(self, current, target))
    service.close_position(position_id, price=1.11, timestamp=NOW)
    assert PositionState.EXIT_PENDING in seen and PositionState.CLOSED in seen


# ------------------------------------------------------------------ time exit
def exit_engine():
    return TimeExitEngine(timezone_engine=TradingSessionEngine(timezone="UTC"))


def test_time_exit_closes_a_position_when_structure_is_invalidated():
    service, position_id = open_position()
    decision = service.evaluate_exit(position_id, engine=exit_engine(), timestamp=NOW,
                                     structure_valid=False, regime_valid=True, risk_allowed=True,
                                     confidence=.8, price=1.11)
    assert decision.action is ExitAction.INVALIDATE
    assert position_id not in service.positions
    assert service.journals[-1].final_result is not None
    assert "EXIT_STRUCTURE_INVALIDATED" in service.journals[-1].exit_reason


def test_time_exit_holds_a_healthy_position():
    service, position_id = open_position()
    decision = service.evaluate_exit(position_id, engine=exit_engine(), timestamp=NOW,
                                     structure_valid=True, regime_valid=True, risk_allowed=True,
                                     confidence=.9, price=1.11, next_even_hour_only=False)
    assert decision.action is ExitAction.HOLD
    assert position_id in service.positions


def test_time_exit_reduce_keeps_the_position_but_records_the_reduce():
    service, position_id = open_position()
    decision = service.evaluate_exit(position_id, engine=exit_engine(), timestamp=NOW,
                                     structure_valid=True, regime_valid=True, risk_allowed=True,
                                     confidence=.1, price=1.11, next_even_hour_only=False)
    assert decision.action is ExitAction.REDUCE
    assert service.positions[position_id].state is PositionState.OPEN


# ------------------------------------------------------------ journal write-back
def test_closing_the_first_of_two_trades_persists_that_trade_not_the_last(db_session):
    """The write-back bug persisted journals[-1] regardless of which trade closed."""
    service = PaperTradingService(repository=PaperTradingRepository(db_session))
    service.start()
    first = service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                          risk_decision=RISK_OK, data_quality="VALID", provider_status="ONLINE",
                          prediction=PRED).order.position_id
    second_request = PaperOrderRequest("GBPUSD", Direction.LONG, OrderType.MARKET, 1., NOW,
                                       source_timestamp=NOW)
    second = service.enter(second_request, quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                           risk_decision=RISK_OK, data_quality="VALID", provider_status="ONLINE",
                           prediction=PRED).order.position_id
    assert first != second

    service.close_position(first, price=1.11, timestamp=NOW, reason=("WHY_EXIT:FIRST",))

    stored = {row.trade_id: row.journal_json for row in db_session.query(PaperTradeJournalRecord).all()}
    assert stored[first]["final_result"] is not None
    assert stored[first]["exit_reason"] == ["WHY_EXIT:FIRST"]
    assert stored[second]["final_result"] is None


# ------------------------------------------------------------------ persistence
def test_paper_state_survives_a_restart(db_session):
    repository = PaperTradingRepository(db_session)
    service = PaperTradingService(repository=repository)
    service.start()
    _, position_id = open_position(service)
    service.mark(position_id, 1.105, NOW)

    restarted = PaperTradingService().restore(repository)

    assert position_id in restarted.positions
    reopened = restarted.positions[position_id]
    assert reopened.symbol == "EURUSD" and reopened.state is PositionState.OPEN
    assert reopened.quantity == 1.
    assert restarted.orders and restarted.orders[0].position_id == position_id
    assert restarted.journals and restarted.journals[0].trade_id == position_id
    assert restarted.equity_curve
    assert restarted.account.balance == service.account.balance


def test_a_closed_position_is_not_restored_into_the_open_book(db_session):
    repository = PaperTradingRepository(db_session)
    service = PaperTradingService(repository=repository)
    service.start()
    _, position_id = open_position(service)
    service.close_position(position_id, price=1.11, timestamp=NOW)

    restarted = PaperTradingService().restore(repository)
    assert not restarted.positions
    assert restarted.journals[0].final_result is not None
    assert db_session.query(PaperPositionRecord).one().state == "CLOSED"


def test_bound_repository_restores_the_previous_binding(db_session):
    service = PaperTradingService()
    assert service.repository is None
    with bound_repository(service, PaperTradingRepository(db_session)):
        assert service.repository is not None
    assert service.repository is None
