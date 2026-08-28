"""AI feedback after a DEMO trade closes (sections 30 and 31).

The outcome goes to the observation/performance pipeline, and that is the whole
of it. Nothing fits a model, updates a weight, promotes a champion or schedules a
training run — a live trade result is exactly the input that would tempt a system
into learning inside the market loop.
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings
from database.models import DemoTradeJournalRecord, ObservationPerformanceRecord
from database.repositories.demo import DemoTradingRepository
from execution.demo.feedback import EVIDENCE_SOURCE, DemoFeedbackPublisher, DemoTradeFeedback
from execution.demo.journal import DemoTradeJournal
from execution.demo.performance import calculate_demo_performance
from execution.mt5.order_result import ExecutionStatus, OrderResult
from tests.phase16_helpers import BASE, LONDON_MOMENT, live_context, order, service_for
from datetime import timedelta


def closed_entry(journal=None, **overrides):
    journal = journal or DemoTradeJournal()
    request = order()
    result = OrderResult(request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
                         filled_volume=0.02, requested_price=1.10024, filled_price=1.10030,
                         broker_ticket=700001)
    journal.open(request=request, result=result, market_snapshot={"spread": 0.00012},
                 feature_snapshot={"rsi": 55.0}, nn_prediction={"confidence": 0.72,
                                                                "direction": "UP"},
                 strategy_decision={"decision": "SIMULATE"}, risk_decision={"risk_allowed": True},
                 session="LONDON", regime="BULL", now=LONDON_MOMENT)
    payload = dict(exit_reason="TAKE_PROFIT", pnl=12.5, gross_pnl=13.45, mae=-0.0008,
                   mfe=0.0031, commission=-0.8, swap=-0.15,
                   now=LONDON_MOMENT + timedelta(hours=2))
    payload.update(overrides)
    return journal, journal.close(request.request_id, **payload)


# ---------------------------------------------------------------- the journal
def test_a_journal_entry_records_the_whole_chain_of_custody():
    """Section 20, field for field."""
    _, entry = closed_entry()
    payload = entry.as_dict()
    for name in ("market_snapshot", "feature_snapshot", "nn_prediction", "strategy_decision",
                 "risk_decision", "execution_request", "execution_result", "mt5_result",
                 "position_lifecycle", "exit_reason", "pnl", "mae", "mfe", "session",
                 "regime", "model_version", "strategy_version", "feature_version"):
        assert name in payload


def test_an_entry_without_its_versions_is_not_complete():
    journal = DemoTradeJournal()
    request = order(model_version=None, strategy_version=None, feature_version=None)
    result = OrderResult(request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
                         filled_volume=0.02, filled_price=1.1003, broker_ticket=1)
    entry = journal.open(request=request, result=result, market_snapshot={"a": 1},
                         feature_snapshot={"b": 2}, strategy_decision={"c": 3},
                         risk_decision={"d": 4})
    assert not entry.complete
    assert {"model_version", "strategy_version", "feature_version"} <= set(entry.missing)


def test_a_complete_entry_reports_itself_complete():
    _, entry = closed_entry()
    assert entry.complete and entry.missing == ()


def test_closing_without_a_reason_is_refused():
    journal, _ = closed_entry()
    with pytest.raises(ValueError, match="exit reason"):
        journal.close(journal.entries[0].trade_id, exit_reason="")


def test_the_position_lifecycle_is_recorded():
    from execution.demo.monitor import PositionMonitor
    from types import SimpleNamespace

    journal, entry = closed_entry()
    monitor = PositionMonitor()
    snapshot = monitor.update(SimpleNamespace(
        ticket=700001, symbol="EURUSD", direction="BUY", volume=0.02, open_price=1.1003,
        current_price=1.1020, profit=3.4, open_time=LONDON_MOMENT))
    updated = journal.record_position(entry.trade_id, snapshot)
    assert len(updated.position_lifecycle) == 1


def test_slippage_is_derived_from_the_fill():
    _, entry = closed_entry()
    assert entry.slippage == pytest.approx(0.00006)


# --------------------------------------------------------------- the feedback
def test_the_feedback_never_reports_a_retrain():
    _, entry = closed_entry()
    feedback = DemoFeedbackPublisher.from_journal(entry, exit_price=1.1050)
    assert feedback.retrained is False and feedback.promoted is False
    assert feedback.as_dict()["retrained"] is False


def test_the_feedback_is_tagged_as_demo_execution():
    """A real fill is never silently mixed into hypothetical observations."""
    _, entry = closed_entry()
    feedback = DemoFeedbackPublisher.from_journal(entry)
    assert feedback.evidence == EVIDENCE_SOURCE


def test_the_feedback_carries_the_outcome_and_its_versions():
    _, entry = closed_entry()
    feedback = DemoFeedbackPublisher.from_journal(entry, exit_price=1.1050)
    assert feedback.net_pnl == 12.5 and feedback.mae == -0.0008 and feedback.mfe == 0.0031
    assert feedback.exit_reason == "TAKE_PROFIT"
    assert feedback.model_version == "model-1" and feedback.feature_version == "features_v1"
    assert feedback.holding_seconds == pytest.approx(7200.0)


def test_the_prediction_is_scored_against_the_outcome():
    _, entry = closed_entry()
    correct = DemoFeedbackPublisher.from_journal(entry)
    assert correct.prediction_correct is True

    _, losing = closed_entry(pnl=-4.0)
    assert DemoFeedbackPublisher.from_journal(losing).prediction_correct is False


def test_an_unscoreable_prediction_reports_none():
    feedback = DemoTradeFeedback("t1", "EURUSD", "BUY", 1.1, 1.1, None, None, None, None,
                                 None, None)
    assert feedback.prediction_correct is None


def test_publishing_records_the_outcome_without_training(db_session):
    _, entry = closed_entry()
    publisher = DemoFeedbackPublisher(DemoTradingRepository(db_session))
    published = publisher.publish_journal(entry, exit_price=1.1050)

    row = db_session.query(ObservationPerformanceRecord).one()
    assert row.symbol == "EURUSD" and row.hypothetical_pnl == pytest.approx(12.5)
    assert row.record_json["retrained"] is False
    assert row.record_json["evidence"] == EVIDENCE_SOURCE
    assert published.retrained is False


def test_the_publisher_has_no_way_to_train():
    for name in ("train", "fit", "retrain", "promote", "update_weights"):
        assert not hasattr(DemoFeedbackPublisher, name)


def test_online_learning_and_automatic_training_remain_refused():
    """Phase 13/14 invariants; a DEMO fill must not become a reason to relax them."""
    with pytest.raises(ValidationError, match="AI_ONLINE_LEARNING_ENABLED"):
        Settings(**BASE, ai_online_learning_enabled=True)
    with pytest.raises(ValidationError, match="AI_AUTOMATIC_TRAINING"):
        Settings(**BASE, ai_automatic_training=True)


# ------------------------------------------------------------ the performance
def test_performance_needs_closed_trades():
    performance = calculate_demo_performance([])
    assert performance.samples == 0 and not performance.reliable
    assert "NO_CLOSED_DEMO_TRADES" in performance.reasons


def test_open_trades_are_excluded_rather_than_counted_as_flat():
    journal = DemoTradeJournal()
    request = order()
    journal.open(request=request, result=OrderResult(
        request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
        filled_volume=0.02, filled_price=1.1003, broker_ticket=1))
    assert calculate_demo_performance(journal.entries).samples == 0


def test_performance_reports_the_trading_and_execution_metrics():
    journal = DemoTradeJournal()
    for index, pnl in enumerate((10.0, -5.0, 7.5)):
        request = order(signal_id=f"signal-{index}")
        journal.open(request=request, result=OrderResult(
            request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
            filled_volume=0.02, requested_price=1.1000, filled_price=1.1001, broker_ticket=index))
        journal.close(request.request_id, exit_reason="TAKE_PROFIT", pnl=pnl, gross_pnl=pnl + 1,
                      mae=-0.001, mfe=0.002, commission=-0.8, swap=-0.1)

    performance = calculate_demo_performance(journal.entries, orders_submitted=3,
                                             orders_rejected=1, reconciliation_errors=0)
    assert performance.samples == 3 and performance.wins == 2 and performance.losses == 1
    assert performance.win_rate == pytest.approx(2 / 3, abs=1e-4)
    assert performance.net_pnl == pytest.approx(12.5)
    assert performance.profit_factor == pytest.approx(3.5)
    assert performance.rejection_rate == pytest.approx(0.25)
    assert performance.average_slippage == pytest.approx(0.0001)
    assert performance.total_commission == pytest.approx(-2.4)
    assert not performance.reliable, "three trades is an anecdote"


def test_performance_groups_by_strategy_and_model():
    journal = DemoTradeJournal()
    for index in range(2):
        request = order(signal_id=f"signal-{index}")
        journal.open(request=request, result=OrderResult(
            request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
            filled_volume=0.02, filled_price=1.1001, broker_ticket=index))
        journal.close(request.request_id, exit_reason="TIME_EXIT", pnl=1.0)
    performance = calculate_demo_performance(journal.entries)
    assert performance.by_strategy["phase6.strategy.v1"]["samples"] == 2
    assert performance.by_model["model-1"]["samples"] == 2


# ---------------------------------------------------------------- end to end
def test_a_filled_demo_trade_opens_a_journal_entry(db_session):
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed

    row = db_session.get(DemoTradeJournalRecord, request.request_id)
    assert row is not None and row.broker_ticket == 700001 and row.closed is False


def test_closing_a_demo_trade_feeds_the_performance_pipeline(db_session):
    service, _ = service_for(db_session)
    request = order()
    service.submit(request, live_context(service, request))

    service.journal.close(request.request_id, exit_reason="TAKE_PROFIT", pnl=9.0,
                          gross_pnl=10.0, mae=-0.0005, mfe=0.0022)
    service.feedback.publish_journal(service.journal.get(request.request_id))

    row = db_session.query(ObservationPerformanceRecord).one()
    assert row.record_json["retrained"] is False
    assert service.performance()["samples"] == 1
