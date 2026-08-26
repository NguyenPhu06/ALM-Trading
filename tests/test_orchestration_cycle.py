"""The orchestration cycle: one closed-candle tick, end to end.

Phase 9 had no loop at all — the strategy engine, the inference engine and the
paper service were only ever called from tests, so every dashboard panel
downstream of strategy was permanently empty.
"""
from datetime import timedelta

import pytest

from database.models import (
    DashboardAlertRecord,
    PaperOrderRecord,
    PredictionRecord,
    StrategyDecisionRecord,
    StrategyMarketSnapshot,
    TradeSetupRecord,
)
from database.repositories import PaperTradingRepository
from orchestration import OrchestrationCycle, Stage
from paper import PaperTradingService
from tests.phase9_helpers import NOW, StubInference, seed_market


@pytest.fixture()
def paper():
    service = PaperTradingService()
    service.start()
    return service


def cycle_for(db_session, paper, **kwargs):
    return OrchestrationCycle(db_session, paper_service=paper, now=NOW, **kwargs)


# ---------------------------------------------------------------- the green path
def test_full_cycle_runs_data_to_paper_execution_and_persists_every_stage(db_session, paper):
    seed_market(db_session)
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")

    assert result.stage is Stage.COMPLETED and not result.halted
    assert result.data_quality == "VALID" and result.provider_status == "ONLINE"
    assert result.model_status == "ONLINE"
    assert result.decision == "SIMULATE" and result.setup_status == "EXECUTABLE_SIMULATION"
    assert result.executed.accepted and len(paper.positions) == 1

    assert db_session.query(StrategyMarketSnapshot).count() == 1
    assert db_session.query(TradeSetupRecord).count() == 1
    assert db_session.query(StrategyDecisionRecord).count() == 1
    assert db_session.query(PredictionRecord).count() == 1

    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert {"STRATEGY_READY", "PAPER_ENTRY"} <= types


def test_setup_and_decision_rows_carry_the_backend_explanation(db_session, paper):
    seed_market(db_session)
    cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    setup = db_session.query(TradeSetupRecord).one()
    decision = db_session.query(StrategyDecisionRecord).one()
    assert setup.status == "EXECUTABLE_SIMULATION" and setup.direction == "LONG"
    assert setup.score >= 75 and setup.model_version == "test_mlp.v1"
    assert decision.setup_id == setup.setup_id and decision.decision == "SIMULATE"
    assert any(code.startswith("HTF_") for code in decision.decision_json["reason_codes"])


# ------------------------------------------------------- model-unavailable safety
def test_without_a_trained_model_the_cycle_refuses_to_trade(db_session, paper):
    """No model means no entry — never a fabricated or default probability."""
    seed_market(db_session)
    result = cycle_for(db_session, paper).run("EURUSD")

    assert result.model_status == "UNAVAILABLE" and result.prediction is None
    assert result.decision == "INVALIDATE" and result.setup_status == "INVALID"
    assert "MODEL_UNAVAILABLE" in result.reason_codes
    assert result.executed is None and not paper.positions
    assert db_session.query(PredictionRecord).count() == 0
    assert db_session.query(DashboardAlertRecord).one().alert_type == "STRATEGY_INVALIDATED"


def test_a_model_returning_a_future_prediction_is_discarded_not_used(db_session, paper):
    seed_market(db_session)
    future = StubInference(offset=timedelta(minutes=30))
    result = cycle_for(db_session, paper, inference=future).run("EURUSD")

    assert result.model_status == "UNAVAILABLE" and result.prediction is None
    assert result.decision == "INVALIDATE" and not paper.positions
    assert db_session.query(PredictionRecord).count() == 0


# ------------------------------------------------------------------ data gating
def test_an_empty_database_halts_before_strategy_and_opens_nothing(db_session, paper):
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    assert result.halted and result.stage in {Stage.VALIDATION, Stage.INTELLIGENCE}
    assert result.executed is None and not paper.positions
    assert db_session.query(StrategyDecisionRecord).count() == 0


def test_invalid_market_data_halts_at_validation_and_raises_an_alert(db_session, paper):
    seed_market(db_session, counts=(("M5", 3),))
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    assert result.halted and result.stage is Stage.VALIDATION
    assert not paper.positions
    alerts = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert alerts and alerts <= {"DATA_ERROR", "PROVIDER_ERROR"}


def test_only_closed_candles_reach_the_cycle(db_session, paper):
    """An unclosed candle stamped after the tick must not move the source timestamp."""
    seed_market(db_session)
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    assert result.source_timestamp is not None and result.source_timestamp <= NOW


def test_the_same_closed_candle_is_never_evaluated_twice(db_session, paper):
    seed_market(db_session)
    cycle = cycle_for(db_session, paper, inference=StubInference())
    first = cycle.run("EURUSD")
    second = cycle.run("EURUSD")
    assert first.stage is Stage.COMPLETED
    assert second.halted and "ALREADY_EVALUATED_THIS_CANDLE" in second.reason_codes
    assert len(paper.positions) == 1
    assert db_session.query(StrategyDecisionRecord).count() == 1


# ------------------------------------------------------------- execution gating
def test_the_kill_switch_stops_the_loop_from_entering(db_session, paper):
    seed_market(db_session)
    paper.risk.kill_switch.activate()
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")

    assert result.decision == "SIMULATE"
    assert not result.executed.accepted and result.executed.rejection_reason == "GLOBAL_KILL_SWITCH"
    assert not paper.positions
    alerts = {row.alert_type: row for row in db_session.query(DashboardAlertRecord).all()}
    assert alerts["RISK_BLOCK"].severity == "CRITICAL"


def test_a_stopped_paper_service_never_receives_an_order(db_session, paper):
    seed_market(db_session)
    paper.stop()
    result = cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    assert "PAPER_TRADING_NOT_RUNNING" in result.reason_codes
    assert result.executed is None and not paper.positions


def test_the_loop_does_not_stack_a_second_position_on_the_same_symbol(db_session, paper):
    seed_market(db_session)
    cycle = cycle_for(db_session, paper, inference=StubInference())
    cycle.run("EURUSD")
    cycle._last_processed.clear()          # simulate the next tick on a fresh bar
    result = cycle.run("EURUSD")
    assert "HOLDING_OPEN_POSITION" in result.reason_codes
    assert len(paper.positions) == 1


# ------------------------------------------------------------------- paper only
def test_the_cycle_exposes_no_broker_or_live_environment(db_session, paper):
    seed_market(db_session)
    cycle = cycle_for(db_session, paper, inference=StubInference())
    result = cycle.run("EURUSD")
    assert result.environment == "PAPER"
    assert not hasattr(cycle, "broker") and not hasattr(cycle, "live")
    assert not paper.execution.safety.live_trading_enabled


def test_orders_produced_by_the_loop_are_persisted_for_restart(db_session, paper):
    seed_market(db_session)
    paper.repository = PaperTradingRepository(db_session)
    cycle_for(db_session, paper, inference=StubInference()).run("EURUSD")
    assert db_session.query(PaperOrderRecord).count() == 1
