"""Strategy registry (section 1).

A strategy is a *declaration*: which features it reads, which timeframes it
looks at, and what its entry, exit, DCA and risk rules are. The registry stores
that declaration and the state it has earned. It never executes a rule.

The state machine mirrors the model registry's on purpose — a strategy and a
model earn their way to CHAMPION through the same evidence, and neither gets
there without a named human.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence


class StrategyStatus(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    TESTING = "TESTING"
    VALIDATED = "VALIDATED"
    CHAMPION = "CHAMPION"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


# Forward only, and never straight to CHAMPION from an untested state.
ALLOWED_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.EXPERIMENTAL: frozenset({StrategyStatus.TESTING,
                                            StrategyStatus.REJECTED}),
    StrategyStatus.TESTING: frozenset({StrategyStatus.VALIDATED,
                                       StrategyStatus.REJECTED}),
    StrategyStatus.VALIDATED: frozenset({StrategyStatus.CHAMPION,
                                         StrategyStatus.REJECTED,
                                         StrategyStatus.RETIRED}),
    StrategyStatus.CHAMPION: frozenset({StrategyStatus.RETIRED,
                                        StrategyStatus.REJECTED}),
    StrategyStatus.REJECTED: frozenset(),
    StrategyStatus.RETIRED: frozenset(),
}


class TransitionRefused(RuntimeError):
    """Raised when a strategy is asked to skip, repeat or reverse a state."""


class PromotionRefused(RuntimeError):
    """Raised when a promotion is attempted without a named human."""


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    approved_by: str
    reason: str
    approved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not str(self.approved_by).strip():
            raise ValueError("promotion requires a named human approver")
        if not str(self.reason).strip():
            raise ValueError("promotion requires a stated reason")

    def as_dict(self) -> dict[str, Any]:
        return {"approved_by": self.approved_by, "reason": self.reason,
                "approved_at": self.approved_at.isoformat()}


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    strategy_id: str
    strategy_version: str
    description: str
    features: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    entry_rules: tuple[str, ...] = ()
    exit_rules: tuple[str, ...] = ()
    dca_rules: tuple[str, ...] = ()
    risk_rules: tuple[str, ...] = ()
    status: StrategyStatus = StrategyStatus.EXPERIMENTAL
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None
    approval: ApprovalToken | None = None
    notes: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.strategy_id}:{self.strategy_version}"

    @property
    def is_champion(self) -> bool:
        return self.status is StrategyStatus.CHAMPION

    @property
    def fingerprint(self) -> str:
        """Content hash of the declaration — two identical strategies collide."""
        payload = json.dumps({
            "features": sorted(self.features), "timeframes": sorted(self.timeframes),
            "entry_rules": sorted(self.entry_rules), "exit_rules": sorted(self.exit_rules),
            "dca_rules": sorted(self.dca_rules), "risk_rules": sorted(self.risk_rules),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
            "key": self.key, "description": self.description,
            "features": list(self.features), "timeframes": list(self.timeframes),
            "entry_rules": list(self.entry_rules), "exit_rules": list(self.exit_rules),
            "dca_rules": list(self.dca_rules), "risk_rules": list(self.risk_rules),
            "status": str(self.status), "fingerprint": self.fingerprint,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "approval": self.approval.as_dict() if self.approval else None,
            "notes": list(self.notes),
            # Stated so no reader can mistake a registry entry for a live strategy.
            "executes": False,
        }


def strategy(strategy_id: str, description: str, *, version: str = "v1",
             features: Sequence[str] = (), timeframes: Sequence[str] = (),
             entry_rules: Sequence[str] = (), exit_rules: Sequence[str] = (),
             dca_rules: Sequence[str] = (), risk_rules: Sequence[str] = (),
             **extra: Any) -> StrategyRecord:
    return StrategyRecord(
        strategy_id=strategy_id, strategy_version=version, description=description,
        features=tuple(features), timeframes=tuple(timeframes),
        entry_rules=tuple(entry_rules), exit_rules=tuple(exit_rules),
        dca_rules=tuple(dca_rules), risk_rules=tuple(risk_rules), context=dict(extra))


class StrategyRegistry:
    """Stores declarations and the state each has earned. Executes nothing."""

    def __init__(self, repository: Any = None):
        self.repository = repository
        self._records: dict[str, StrategyRecord] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------ write
    def register(self, record: StrategyRecord) -> StrategyRecord:
        if record.key in self._records:
            raise ValueError(f"strategy already registered: {record.key}")
        self._records[record.key] = record
        self._order.append(record.key)
        self._persist(record)
        return record

    def transition(self, key: str, status: StrategyStatus, *,
                   note: str | None = None) -> StrategyRecord:
        record = self.get(key)
        target = StrategyStatus(status)
        if target not in ALLOWED_TRANSITIONS.get(record.status, frozenset()):
            raise TransitionRefused(f"{record.status} -> {target} is not allowed")
        if target is StrategyStatus.CHAMPION:
            raise PromotionRefused("use promote(): CHAMPION requires an ApprovalToken")
        updated = replace(record, status=target, updated_at=_utcnow(),
                          notes=(*record.notes, note) if note else record.notes)
        self._records[key] = updated
        self._persist(updated)
        return updated

    def reject(self, key: str, reason: str) -> StrategyRecord:
        """Section 10: rejection is a recorded decision with a stated reason."""
        if not str(reason).strip():
            raise ValueError("rejecting a strategy requires a stated reason")
        return self.transition(key, StrategyStatus.REJECTED, note=f"REJECTED:{reason}")

    def promote(self, key: str, token: ApprovalToken) -> StrategyRecord:
        """Section 4: no automatic promotion, ever."""
        record = self.get(key)
        if record.status is not StrategyStatus.VALIDATED:
            raise PromotionRefused(
                f"only a VALIDATED strategy may be promoted; {key} is {record.status}")
        if not isinstance(token, ApprovalToken):
            raise PromotionRefused("promotion requires an ApprovalToken")

        # One champion per strategy_id: the incumbent retires first.
        for other_key, other in list(self._records.items()):
            if (other.strategy_id == record.strategy_id and other.is_champion
                    and other_key != key):
                retired = replace(other, status=StrategyStatus.RETIRED,
                                  updated_at=_utcnow(),
                                  notes=(*other.notes, f"SUPERSEDED_BY:{key}"))
                self._records[other_key] = retired
                self._persist(retired)

        promoted = replace(record, status=StrategyStatus.CHAMPION, updated_at=_utcnow(),
                           approval=token,
                           notes=(*record.notes, f"PROMOTED_BY:{token.approved_by}"))
        self._records[key] = promoted
        self._persist(promoted)
        return promoted

    # ------------------------------------------------------------------- read
    def get(self, key: str) -> StrategyRecord:
        if key not in self._records:
            raise KeyError(f"unknown strategy: {key}")
        return self._records[key]

    def all(self) -> list[StrategyRecord]:
        return [self._records[key] for key in self._order]

    def by_status(self, status: StrategyStatus) -> list[StrategyRecord]:
        return [record for record in self.all() if record.status is StrategyStatus(status)]

    def champion(self, strategy_id: str | None = None) -> StrategyRecord | None:
        for record in self.all():
            if record.is_champion and (strategy_id is None
                                       or record.strategy_id == strategy_id):
                return record
        return None

    def challengers(self, strategy_id: str | None = None) -> list[StrategyRecord]:
        return [record for record in self.all()
                if record.status in {StrategyStatus.VALIDATED, StrategyStatus.TESTING}
                and (strategy_id is None or record.strategy_id == strategy_id)]

    def duplicates(self) -> dict[str, list[str]]:
        """Declarations that are identical apart from their name."""
        seen: dict[str, list[str]] = {}
        for record in self.all():
            seen.setdefault(record.fingerprint, []).append(record.key)
        return {digest: keys for digest, keys in seen.items() if len(keys) > 1}

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.all():
            counts[str(record.status)] = counts.get(str(record.status), 0) + 1
        champion = self.champion()
        return {"total": len(self._records), "by_status": counts,
                "champion": champion.key if champion else None,
                "challengers": [record.key for record in self.challengers()],
                "duplicates": self.duplicates()}

    # ---------------------------------------------------------------- persist
    def _persist(self, record: StrategyRecord) -> None:
        if self.repository is None:
            return
        saver = getattr(self.repository, "save_strategy", None)
        if saver is not None:
            saver(record)

    def load(self, records: Sequence[StrategyRecord | Mapping[str, Any]]) -> int:
        for item in records:
            record = item if isinstance(item, StrategyRecord) else from_dict(item)
            self._records[record.key] = record
            if record.key not in self._order:
                self._order.append(record.key)
        return len(self._records)


def from_dict(payload: Mapping[str, Any]) -> StrategyRecord:
    return StrategyRecord(
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload.get("strategy_version", "v1")),
        description=str(payload.get("description", "")),
        features=tuple(payload.get("features") or ()),
        timeframes=tuple(payload.get("timeframes") or ()),
        entry_rules=tuple(payload.get("entry_rules") or ()),
        exit_rules=tuple(payload.get("exit_rules") or ()),
        dca_rules=tuple(payload.get("dca_rules") or ()),
        risk_rules=tuple(payload.get("risk_rules") or ()),
        status=StrategyStatus(payload.get("status", "EXPERIMENTAL")),
        notes=tuple(payload.get("notes") or ()))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
