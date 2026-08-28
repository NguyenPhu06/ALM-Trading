"""SHADOW/DEMO parity (section 2).

    "Do not maintain separate trading logic."

This is the file that holds that line. A shadow record is minted from the same
`GateChainDecision` the DEMO path produced, on the same code path, so the two
cannot disagree about market data, features, inference, strategy, risk or the
execution proposal. The only difference is the broker call.

The strongest tests here are the structural ones: the same request run through
SHADOW and DEMO must produce identical decisions and identical shadow records,
and nothing under `validation/` may import an execution client.
"""
import ast
import inspect
import pathlib

import pytest

from execution.demo.gates import (
    DECISION_GATES, GATE_ORDER, TRANSMISSION_GATES, DemoGateChain,
)
from execution.demo.modes import ExecutionMode
from tests.phase16_helpers import armed, chain_for, context, live_context, order, service_for
from tests.phase17_helpers import shadow_settings
from validation.shadow import ShadowRecorder, shadow_signal_id

VALIDATION = pathlib.Path(__file__).resolve().parents[1] / "validation"

FORBIDDEN_IMPORTS = ("MT5ExecutionClient", "MT5Connection", "send_market_order",
                     "order_send", "PaperExecutionEngine")


# ------------------------------------------------------- one decision, two views
def test_shadow_and_demo_run_the_same_gates_in_the_same_order():
    request = order()
    ctx = context()
    shadow_decision = chain_for(shadow_settings()).evaluate(request, ctx)
    demo_decision = chain_for(armed()).evaluate(request, ctx)

    assert ([gate.name for gate in shadow_decision.gates]
            == [gate.name for gate in demo_decision.gates]
            == list(GATE_ORDER))


def test_shadow_and_demo_reach_the_same_decision():
    """Every DECISION gate agrees. That is what parity means.

    They differ on the TRANSMISSION gates, and that difference is the mode: those
    gates answer "may this be sent", and SHADOW never sends.
    """
    request = order()
    ctx = context()
    shadow_decision = chain_for(shadow_settings()).evaluate(request, ctx)
    demo_decision = chain_for(armed()).evaluate(request, ctx)

    shadow_verdicts = shadow_decision.verdicts
    demo_verdicts = demo_decision.verdicts
    for name in DECISION_GATES:
        assert shadow_verdicts[name] == demo_verdicts[name], name
    assert shadow_decision.decision_approved is demo_decision.decision_approved is True
    assert shadow_decision.decision_reasons == demo_decision.decision_reasons == ()


def test_only_transmission_separates_the_two_verdicts():
    request = order()
    ctx = context()
    shadow_decision = chain_for(shadow_settings()).evaluate(request, ctx)
    demo_decision = chain_for(armed()).evaluate(request, ctx)

    assert demo_decision.approved is True
    assert shadow_decision.approved is False
    # Everything that separates them is a transmission concern.
    assert set(shadow_decision.blocked_by) <= set(TRANSMISSION_GATES)
    assert "MODE_BLOCKS_EXECUTION" in shadow_decision.reasons


def test_a_refused_decision_is_refused_in_both_modes():
    """Parity has to hold for the refusals too, not only the approvals."""
    request = order()
    ctx = context(risk_allowed=False)
    shadow_decision = chain_for(shadow_settings()).evaluate(request, ctx)
    demo_decision = chain_for(armed()).evaluate(request, ctx)

    assert shadow_decision.decision_approved is demo_decision.decision_approved is False
    assert shadow_decision.decision_reasons == demo_decision.decision_reasons
    assert "RISK_ENGINE_BLOCKED" in shadow_decision.decision_reasons


def test_the_shadow_record_is_minted_from_the_demo_decision():
    """Not recomputed: the record is a view of the decision that was made."""
    request = order()
    ctx = context()
    decision = chain_for(armed()).evaluate(request, ctx)
    signal = ShadowRecorder().record(request, decision, ctx)

    assert signal.demo_execution_request_id == request.request_id
    assert signal.entry == request.price
    assert signal.stop_loss == request.stop_loss and signal.take_profit == request.take_profit
    assert signal.volume == request.volume
    assert signal.strategy_version == request.strategy_version
    assert signal.model_version == request.model_version
    assert signal.feature_version == request.feature_version
    assert signal.confidence == ctx.model_confidence
    assert signal.session == ctx.session
    assert signal.approved is decision.approved
    assert signal.gates == {gate.name: gate.passed for gate in decision.gates}


def test_the_same_request_produces_the_same_shadow_record_in_both_modes():
    request = order()
    ctx = context()
    shadow = ShadowRecorder().record(
        request, chain_for(armed()).evaluate(request, ctx), ctx)
    demo = ShadowRecorder().record(
        request, chain_for(armed()).evaluate(request, ctx), ctx)

    left, right = shadow.as_dict(), demo.as_dict()
    assert left == right


# --------------------------------------------------------------- end to end
def test_every_demo_candidate_produces_a_shadow_record(db_session):
    """Section 3, by construction rather than by convention."""
    from database.models import ShadowSignalRecord

    service, fake = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed and len(fake.sent) == 1

    row = db_session.query(ShadowSignalRecord).one()
    assert row.shadow_signal_id == shadow_signal_id(request.request_id)
    assert row.executed is True, "a transmitted order marks its shadow twin executed"
    assert row.orders_sent == 0


def test_a_blocked_demo_candidate_also_produces_a_shadow_record(db_session):
    """The blocked population is exactly what the gates removed; it must be visible."""
    from database.models import ShadowSignalRecord

    service, fake = service_for(db_session)
    request = order()
    service.submit(request, live_context(service, request, risk_allowed=False))

    assert fake.sent == []
    row = db_session.query(ShadowSignalRecord).one()
    assert row.executed is False and row.approved is False


def test_shadow_and_demo_record_the_same_signal_for_the_same_request(db_session):
    shadow_service, shadow_fake = service_for(db_session, shadow_settings())
    request = order()
    shadow_service.submit(request, live_context(shadow_service, request))
    shadow_record = shadow_service.shadow.for_request(request.request_id)

    assert shadow_fake.sent == []
    assert shadow_record is not None
    assert shadow_record.symbol == request.symbol
    assert shadow_record.side == str(request.side)
    assert shadow_record.entry == request.price


def test_the_shadow_stage_is_in_the_audit_trail(db_session):
    from database.models import ExecutionAuditLogRecord

    service, _ = service_for(db_session, shadow_settings())
    request = order()
    service.submit(request, live_context(service, request))
    stages = {row.stage for row in db_session.query(ExecutionAuditLogRecord).all()}
    assert "SHADOW" in stages


# ------------------------------------------------------------- no second path
def test_no_validation_module_imports_an_execution_client():
    """Parse the code, do not trust the prose."""
    offenders: list[str] = []
    for path in sorted(VALIDATION.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names |= {alias.name for alias in node.names}
        hits = names & set(FORBIDDEN_IMPORTS)
        if hits:
            offenders.append(f"{path.name}: {sorted(hits)}")
    assert offenders == [], offenders


def test_the_shadow_recorder_holds_no_broker_handle():
    live = ShadowRecorder()
    assert not hasattr(live, "client")
    assert not hasattr(live, "guard")
    assert not hasattr(live, "connection")


def test_the_gate_chain_is_the_only_decision_maker():
    """SHADOW does not get its own chain, its own guard or its own limits."""
    source = inspect.getsource(ShadowRecorder)
    for token in ("DemoGateChain", "ExecutionGuard", "evaluate("):
        assert token not in source, f"{token} would be a second decision path"
