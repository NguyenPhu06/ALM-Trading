"""Strategy output vocabulary and its evidence (Phase 12 section 11)."""
import pytest

from observation.simulation import SignalAction
from tests.phase12_helpers import cycle_for
from tests.phase9_helpers import StubInference


@pytest.fixture()
def result(db_session):
    return cycle_for(db_session, inference=StubInference()).run("EURUSD")


def test_the_signal_is_drawn_from_the_documented_vocabulary(result):
    assert result.signal in set(SignalAction)


def test_a_decision_carries_confidence_and_reasons(result):
    strategy = result.snapshot.as_dict()["strategy"]
    assert strategy["decision"] and strategy["reason_codes"]
    assert 0.0 <= float(strategy["confidence"]) <= 1.0
    assert strategy["score"] is not None


def test_a_decision_carries_timeframe_evidence(result):
    reasons = result.snapshot.as_dict()["strategy"]["reason_codes"]
    assert any(code.startswith("HTF_") for code in reasons)
    assert any("M15" in code for code in reasons)


def test_a_decision_carries_market_regime(result):
    regime = result.snapshot.as_dict()["regime"]
    assert regime["regime"] in {"STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR", "UNKNOWN"}
    assert "htf_score" in regime


def test_a_decision_carries_liquidity_and_indicator_context(result):
    payload = result.snapshot.as_dict()
    assert "observed" in payload["liquidity"] and "inferred" in payload["liquidity"]
    assert payload["indicators"].get("M15")


def test_a_decision_carries_nn_probability(result):
    nn = result.snapshot.as_dict()["neural_network"]
    assert nn["prob_up"] and nn["prob_down"] and nn["prob_neutral"]


def test_a_decision_carries_risk_state_and_timestamp(result):
    payload = result.snapshot.as_dict()
    assert "risk_allowed" in payload["risk"]
    assert payload["timestamp"] is not None


def test_no_order_is_sent_for_any_signal(result):
    assert result.orders_sent == 0
    assert result.simulation.orders_sent == 0
    assert result.simulation.blocked


def test_a_buy_signal_still_sends_nothing(db_session):
    result = cycle_for(db_session, inference=StubInference()).run("EURUSD")
    if result.signal is SignalAction.BUY:
        assert result.simulation.execution.value == "BLOCKED"
    assert result.orders_sent == 0


def test_without_a_model_the_strategy_refuses_to_produce_an_entry(db_session):
    """The model-unavailable safety behaviour is preserved from earlier phases."""
    result = cycle_for(db_session, inference=None).run("EURUSD")
    assert result.signal is not SignalAction.BUY
    assert result.signal is not SignalAction.SELL
