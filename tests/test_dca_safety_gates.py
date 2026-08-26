"""DCA increases exposure, so it must clear the same safety gates as a new entry.

Before Phase 9A, PaperTradingService.dca() hardcoded data_quality="VALID",
provider_status="ONLINE" and model_valid=True, and the kill switch only refused
new_entry. These regressions pin the repaired behaviour.
"""
from paper import Direction, GlobalKillSwitch, OrderType, PaperAccount, PaperRiskEngine, PaperTradingService
from tests.phase8_helpers import PRED, QUOTE, RISK_OK, request, running_service


def open_position(service=None):
    service = service or running_service()
    entry = service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                          risk_decision=RISK_OK, data_quality="VALID",
                          provider_status="ONLINE", prediction=PRED)
    assert entry.accepted
    return service, entry.order.position_id


def attempt_dca(service, position_id, **overrides):
    arguments = {"quote": QUOTE, "market_regime": "TRENDING", "structure_state": "VALID",
                 "risk_state": "ALLOWED", "data_quality": "VALID",
                 "provider_status": "ONLINE", "prediction": PRED}
    arguments.update(overrides)
    return service.dca(position_id, request(OrderType.DCA, position_id=position_id), **arguments)


def test_dca_is_refused_when_data_quality_is_not_valid():
    service, position_id = open_position()
    result = attempt_dca(service, position_id, data_quality="INVALID")
    assert not result.accepted and result.rejection_reason == "DATA_QUALITY_INVALID"
    assert service.positions[position_id].dca_entries == 0


def test_dca_is_refused_when_provider_is_not_online():
    for status in ("OFFLINE", "DEGRADED", "UNKNOWN"):
        service, position_id = open_position()
        result = attempt_dca(service, position_id, provider_status=status)
        assert not result.accepted, status
        assert result.rejection_reason == "PROVIDER_UNAVAILABLE", status


def test_dca_is_refused_when_the_model_prediction_is_unusable():
    for prediction in (None, {"prob_up": float("nan"), "prob_down": 0., "prob_neutral": 1.},
                       {"prob_up": .9, "prob_down": .9, "prob_neutral": .9}):
        service, position_id = open_position()
        result = attempt_dca(service, position_id, prediction=prediction)
        assert not result.accepted and result.rejection_reason == "MODEL_FAILURE"


def test_kill_switch_refuses_dca_because_dca_increases_exposure():
    service, position_id = open_position()
    service.risk.kill_switch.activate()
    result = attempt_dca(service, position_id)
    assert not result.accepted and result.rejection_reason == "GLOBAL_KILL_SWITCH"
    assert service.positions[position_id].dca_entries == 0


def test_kill_switch_still_permits_exposure_reducing_management():
    """Getting flat must never be blocked, or the switch would trap an open position."""
    switch = GlobalKillSwitch()
    switch.activate()
    engine = PaperRiskEngine(kill_switch=switch)
    assert not engine.evaluate(new_entry=True).allowed
    assert not engine.evaluate(new_entry=False, increases_exposure=True).allowed
    assert engine.evaluate(new_entry=False).allowed


def test_dca_respects_the_daily_loss_limit_reached_after_entry():
    service = PaperTradingService(account=PaperAccount(initial_balance=1.))
    service.start()
    service, position_id = open_position(service)
    service.mark(position_id, 1.1002, QUOTE["timestamp"])
    service.mark(position_id, 1.0602, QUOTE["timestamp"])
    assert service.daily.daily_drawdown > service.risk.max_daily_loss
    result = attempt_dca(service, position_id)
    assert not result.accepted and result.rejection_reason == "MAXIMUM_DAILY_LOSS"


def test_dca_exposure_counts_every_open_position_not_only_its_own():
    service = PaperTradingService(risk=PaperRiskEngine(max_exposure=2.))
    service.start()
    service, first = open_position(service)
    _, second = open_position(service)
    assert len(service.positions) == 2
    result = attempt_dca(service, first)
    assert not result.accepted and result.rejection_reason == "MAXIMUM_EXPOSURE"


def test_dca_still_succeeds_when_every_gate_is_genuinely_clear():
    service, position_id = open_position()
    result = attempt_dca(service, position_id)
    assert result.accepted and service.positions[position_id].dca_entries == 1
