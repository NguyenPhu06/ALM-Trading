"""Manual approval (section 4).

    Strategy Signal -> Risk Approval -> Execution Proposal -> Human Approval
                    -> Execution Guard -> MT5 DEMO

DEMO_MANUAL_APPROVAL exists so that the entire execution path can be exercised
without automated trading. The proposal is the pause: everything up to it has
already happened, and nothing after it happens without a named human.

Two properties the queue enforces rather than documents:

* an approval names a person and states a reason, exactly like a model promotion;
* a proposal expires, so an approval given hours after the market moved cannot
  be handed to the broker as if it were current.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import load_yaml
from execution.demo.gates import GateChainDecision
from execution.demo.order import DemoOrderRequest
from execution.demo.states import DemoExecutionState

PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
PROPOSAL_NOT_PENDING = "PROPOSAL_NOT_PENDING"
PROPOSAL_BLOCKED = "PROPOSAL_BLOCKED"


class ApprovalRefused(RuntimeError):
    """Raised when an approval is impossible, not merely declined."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True, slots=True)
class ExecutionProposal:
    proposal_id: str
    request: DemoOrderRequest
    decision: GateChainDecision
    state: DemoExecutionState
    created_at: datetime
    expires_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_reason: str | None = None
    rejected_reason: str | None = None
    mode: str = "DEMO_MANUAL_APPROVAL"
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return self.state is DemoExecutionState.PROPOSED

    def expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id, "state": str(self.state), "mode": self.mode,
            "created_at": self.created_at, "expires_at": self.expires_at,
            "approved_by": self.approved_by, "approved_at": self.approved_at,
            "approval_reason": self.approval_reason, "rejected_reason": self.rejected_reason,
            "pending": self.pending, "request": self.request.as_dict(),
            "decision": self.decision.as_dict(), "details": dict(self.details),
        }


class ManualApprovalQueue:
    """In-process queue with optional persistence.

    The repository is written through, never read back into a decision: a
    proposal that this process does not hold is not approvable here, which keeps
    approval and submission in the same process and the same guard.
    """

    def __init__(self, *, ttl_seconds: float | None = None, repository: Any = None):
        config = load_yaml().get("phase_16", {})
        self.ttl = timedelta(seconds=float(
            ttl_seconds if ttl_seconds is not None else config.get("proposal_ttl_seconds", 900)))
        self.repository = repository
        self._proposals: dict[str, ExecutionProposal] = {}

    def _save(self, proposal: ExecutionProposal) -> ExecutionProposal:
        self._proposals[proposal.proposal_id] = proposal
        if self.repository is not None and hasattr(self.repository, "save_proposal"):
            self.repository.save_proposal(proposal)
        return proposal

    def propose(self, request: DemoOrderRequest, decision: GateChainDecision, *,
                now: datetime | None = None, mode: str = "DEMO_MANUAL_APPROVAL",
                **details: Any) -> ExecutionProposal:
        """Record the proposal, approved or not.

        A proposal whose gates already refused is created in BLOCKED, not in
        PROPOSED: there is nothing for a human to approve, and offering the
        button anyway would invite an operator to try to click past a gate.
        """
        moment = now or datetime.now(timezone.utc)
        state = (DemoExecutionState.PROPOSED if decision.approved
                 else DemoExecutionState.BLOCKED)
        return self._save(ExecutionProposal(
            request.request_id, request, decision, state, moment, moment + self.ttl,
            rejected_reason=None if decision.approved else ", ".join(decision.reasons) or None,
            mode=mode, details=details))

    def get(self, proposal_id: str) -> ExecutionProposal | None:
        return self._proposals.get(str(proposal_id))

    def pending(self, *, now: datetime | None = None) -> tuple[ExecutionProposal, ...]:
        moment = now or datetime.now(timezone.utc)
        return tuple(proposal for proposal in self._proposals.values()
                     if proposal.pending and not proposal.expired(moment))

    def approve(self, proposal_id: str, *, approved_by: str, reason: str,
                now: datetime | None = None) -> ExecutionProposal:
        if not str(approved_by).strip():
            raise ValueError("manual approval requires a named human approver")
        if not str(reason).strip():
            raise ValueError("manual approval requires a stated reason")
        moment = now or datetime.now(timezone.utc)
        proposal = self.get(proposal_id)
        if proposal is None:
            raise ApprovalRefused(PROPOSAL_NOT_FOUND, f"no proposal {proposal_id}")
        if proposal.state is DemoExecutionState.BLOCKED:
            raise ApprovalRefused(PROPOSAL_BLOCKED,
                                  "a blocked proposal cannot be approved; the gates refused it")
        if not proposal.pending:
            raise ApprovalRefused(PROPOSAL_NOT_PENDING, f"proposal is {proposal.state}")
        if proposal.expired(moment):
            expired = replace(proposal, state=DemoExecutionState.CANCELLED,
                              rejected_reason=PROPOSAL_EXPIRED)
            self._save(expired)
            raise ApprovalRefused(PROPOSAL_EXPIRED, "the proposal expired before it was approved")
        return self._save(replace(proposal, state=DemoExecutionState.APPROVED,
                                  approved_by=str(approved_by), approved_at=moment,
                                  approval_reason=str(reason)))

    def reject(self, proposal_id: str, *, reason: str, actor: str = "operator",
               now: datetime | None = None) -> ExecutionProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise ApprovalRefused(PROPOSAL_NOT_FOUND, f"no proposal {proposal_id}")
        if not proposal.pending:
            raise ApprovalRefused(PROPOSAL_NOT_PENDING, f"proposal is {proposal.state}")
        return self._save(replace(proposal, state=DemoExecutionState.CANCELLED,
                                  rejected_reason=str(reason), approved_by=None,
                                  approved_at=now or datetime.now(timezone.utc),
                                  details={**proposal.details, "rejected_by": actor}))

    def mark(self, proposal_id: str, state: DemoExecutionState, **details: Any) -> ExecutionProposal | None:
        """Record where an approved proposal ended up. Never re-opens one."""
        proposal = self.get(proposal_id)
        if proposal is None:
            return None
        return self._save(replace(proposal, state=DemoExecutionState(state),
                                  details={**proposal.details, **details}))
