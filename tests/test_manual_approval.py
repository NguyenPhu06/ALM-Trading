"""Manual approval (section 4).

    Strategy Signal -> Risk Approval -> Execution Proposal -> Human Approval
                    -> Execution Guard -> MT5 DEMO

The mode exists so the whole path can be exercised with a human in it. Two things
must therefore be true: submitting alone never reaches the broker, and approving
names a person.
"""
import pytest

from database.models import DemoExecutionProposalRecord
from execution.demo.approval import (
    ApprovalRefused, ManualApprovalQueue, PROPOSAL_BLOCKED, PROPOSAL_EXPIRED,
    PROPOSAL_NOT_FOUND, PROPOSAL_NOT_PENDING,
)
from execution.demo.states import DemoExecutionState
from tests.phase16_helpers import (
    APPROVAL_MOMENT, LONDON_MOMENT, armed, chain_for, context, live_context, manual,
    order, service_for,
)
from datetime import timedelta


def queue_with(decision=None, request=None, **kwargs):
    request = request or order()
    decision = decision if decision is not None else chain_for(armed()).evaluate(request, context())
    queue = ManualApprovalQueue(**kwargs)
    return queue, queue.propose(request, decision, now=LONDON_MOMENT), request


# ---------------------------------------------------------------- the queue
def test_an_approved_gate_chain_creates_a_pending_proposal():
    queue, proposal, _ = queue_with()
    assert proposal.state is DemoExecutionState.PROPOSED and proposal.pending
    assert queue.pending(now=LONDON_MOMENT) == (proposal,)


def test_a_refused_gate_chain_creates_a_blocked_proposal():
    """There is nothing for a human to approve, so the button is never offered."""
    decision = chain_for(armed()).evaluate(order(), context(risk_allowed=False))
    _, proposal, _ = queue_with(decision)
    assert proposal.state is DemoExecutionState.BLOCKED
    assert not proposal.pending and proposal.rejected_reason


def test_a_blocked_proposal_cannot_be_approved():
    decision = chain_for(armed()).evaluate(order(), context(risk_allowed=False))
    queue, proposal, _ = queue_with(decision)
    with pytest.raises(ApprovalRefused) as error:
        queue.approve(proposal.proposal_id, approved_by="operator", reason="looks fine to me")
    assert error.value.code == PROPOSAL_BLOCKED


def test_approval_requires_a_named_human():
    queue, proposal, _ = queue_with()
    with pytest.raises(ValueError, match="named human"):
        queue.approve(proposal.proposal_id, approved_by="  ", reason="a stated reason")


def test_approval_requires_a_reason():
    queue, proposal, _ = queue_with()
    with pytest.raises(ValueError, match="stated reason"):
        queue.approve(proposal.proposal_id, approved_by="operator", reason="")


def test_an_approval_records_who_and_why():
    queue, proposal, _ = queue_with()
    approved = queue.approve(proposal.proposal_id, approved_by="Phu",
                             reason="verified demo account", now=LONDON_MOMENT)
    assert approved.state is DemoExecutionState.APPROVED
    assert approved.approved_by == "Phu" and approved.approval_reason == "verified demo account"


def test_a_proposal_expires():
    """An approval given after the market moved is not a current approval."""
    queue, proposal, _ = queue_with(ttl_seconds=60)
    late = LONDON_MOMENT + timedelta(seconds=61)
    with pytest.raises(ApprovalRefused) as error:
        queue.approve(proposal.proposal_id, approved_by="Phu", reason="late", now=late)
    assert error.value.code == PROPOSAL_EXPIRED
    assert queue.get(proposal.proposal_id).state is DemoExecutionState.CANCELLED


def test_an_expired_proposal_is_not_pending():
    queue, proposal, _ = queue_with(ttl_seconds=60)
    assert queue.pending(now=LONDON_MOMENT + timedelta(seconds=61)) == ()


def test_an_unknown_proposal_is_refused():
    queue, _, _ = queue_with()
    with pytest.raises(ApprovalRefused) as error:
        queue.approve("nope", approved_by="Phu", reason="a stated reason")
    assert error.value.code == PROPOSAL_NOT_FOUND


def test_a_proposal_cannot_be_approved_twice():
    queue, proposal, _ = queue_with()
    queue.approve(proposal.proposal_id, approved_by="Phu", reason="first", now=LONDON_MOMENT)
    with pytest.raises(ApprovalRefused) as error:
        queue.approve(proposal.proposal_id, approved_by="Phu", reason="second", now=LONDON_MOMENT)
    assert error.value.code == PROPOSAL_NOT_PENDING


def test_a_rejected_proposal_is_cancelled():
    queue, proposal, _ = queue_with()
    rejected = queue.reject(proposal.proposal_id, reason="spread widened", actor="Phu")
    assert rejected.state is DemoExecutionState.CANCELLED
    assert rejected.rejected_reason == "spread widened"


# -------------------------------------------------------------- the service
def test_manual_mode_stops_at_the_proposal(db_session):
    service, fake = service_for(db_session, manual())
    request = order()
    outcome = service.submit(request, live_context(service, request))

    assert outcome.approved, outcome.reasons
    assert outcome.state is DemoExecutionState.PROPOSED
    assert not outcome.executed
    assert fake.sent == [], "manual approval mode must not transmit on its own"


def test_approving_transmits(db_session):
    service, fake = service_for(db_session, manual())
    request = order()
    service.submit(request, live_context(service, request))

    outcome = service.approve(request.request_id, approved_by="Phu",
                              reason="verified demo account", now=APPROVAL_MOMENT)
    assert outcome.executed and len(fake.sent) == 1
    assert outcome.state is DemoExecutionState.RECONCILED


def test_rejecting_never_transmits(db_session):
    service, fake = service_for(db_session, manual())
    request = order()
    service.submit(request, live_context(service, request))

    proposal = service.reject(request.request_id, reason="operator declined")
    assert proposal.state is DemoExecutionState.CANCELLED
    assert fake.sent == []


def test_the_proposal_and_its_approver_are_persisted(db_session):
    service, _ = service_for(db_session, manual())
    request = order()
    service.submit(request, live_context(service, request))
    service.approve(request.request_id, approved_by="Phu",
                    reason="verified demo account", now=APPROVAL_MOMENT)

    row = db_session.get(DemoExecutionProposalRecord, request.request_id)
    assert row is not None
    assert row.approved_by == "Phu" and row.approved is True
    assert row.approval_reason == "verified demo account"


def test_the_approval_is_in_the_audit_trail(db_session):
    from database.models import ExecutionAuditLogRecord

    service, _ = service_for(db_session, manual())
    request = order()
    service.submit(request, live_context(service, request))
    service.approve(request.request_id, approved_by="Phu",
                    reason="verified demo account", now=APPROVAL_MOMENT)

    rows = [row for row in db_session.query(ExecutionAuditLogRecord).all()
            if row.stage == "APPROVAL"]
    assert rows and rows[0].actor == "Phu"


def test_the_full_manual_path_is_audited(db_session):
    from database.models import ExecutionAuditLogRecord

    service, _ = service_for(db_session, manual())
    request = order()
    service.submit(request, live_context(service, request))
    service.approve(request.request_id, approved_by="Phu",
                    reason="verified demo account", now=APPROVAL_MOMENT)

    stages = {row.stage for row in db_session.query(ExecutionAuditLogRecord).all()}
    assert {"MODE", "GATES", "PROPOSAL", "APPROVAL", "EXECUTION", "RESULT",
            "RECONCILIATION"} <= stages
