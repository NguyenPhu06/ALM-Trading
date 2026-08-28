"""Even-hour checkpoint validation (section 13).

Two jobs. The first is to *record* what every configured checkpoint saw: trend,
liquidity, structure, Ichimoku, RSI, ADX, the NN, the strategy, risk, the
position state, the decision and its reason. The second is to ask whether those
decisions actually improved outcomes.

The second job is the one that matters, and the default answer is no. A
checkpoint policy is a hypothesis like any other: it earns its place by beating
the counterfactual of having held, on a sample large enough to mean something,
and `NOT_PROVEN` is the honest verdict until it does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from statistics import fmean
from typing import Any, Mapping, Sequence

from config.settings import load_yaml

# The observations a checkpoint must record. A checkpoint missing any of them is
# recorded as incomplete rather than quietly scored.
REQUIRED_OBSERVATIONS = ("trend", "liquidity", "structure", "ichimoku", "rsi", "adx",
                         "nn", "strategy", "risk", "position_state")


class EvenHourVerdict(StrEnum):
    IMPROVES = "IMPROVES"
    NOT_PROVEN = "NOT_PROVEN"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    """One even-hour checkpoint, fully observed."""

    checkpoint_id: str
    symbol: str
    timestamp: datetime
    decision: str
    reason: str
    trend: str | None = None
    liquidity: str | None = None
    structure: str | None = None
    ichimoku: str | None = None
    rsi: float | None = None
    adx: float | None = None
    nn: float | None = None
    strategy: str | None = None
    risk: str | None = None
    position_state: str | None = None
    alignment: str | None = None
    required_confidence: float | None = None
    confidence: float | None = None
    # What actually happened afterwards, filled in when the horizon passes.
    realized_pnl: float | None = None
    counterfactual_pnl: float | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_OBSERVATIONS if getattr(self, name) is None)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def improvement(self) -> float | None:
        """Realized minus the counterfactual of having held. None when unknown."""
        if self.realized_pnl is None or self.counterfactual_pnl is None:
            return None
        return self.realized_pnl - self.counterfactual_pnl

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "symbol": self.symbol,
            "timestamp": self.timestamp, "decision": self.decision, "reason": self.reason,
            "trend": self.trend, "liquidity": self.liquidity, "structure": self.structure,
            "ichimoku": self.ichimoku, "rsi": self.rsi, "adx": self.adx, "nn": self.nn,
            "strategy": self.strategy, "risk": self.risk,
            "position_state": self.position_state, "alignment": self.alignment,
            "required_confidence": self.required_confidence, "confidence": self.confidence,
            "realized_pnl": self.realized_pnl, "counterfactual_pnl": self.counterfactual_pnl,
            "improvement": self.improvement, "complete": self.complete,
            "missing": list(self.missing), "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class EvenHourReport:
    verdict: EvenHourVerdict
    checkpoints: int
    complete: int
    scored: int
    exits: int
    holds: int
    mean_improvement: float | None
    exit_improvement: float | None
    hold_improvement: float | None
    counter_trend_checkpoints: int = 0
    counter_trend_improvement: float | None = None
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict), "checkpoints": self.checkpoints,
            "complete": self.complete, "scored": self.scored, "exits": self.exits,
            "holds": self.holds, "mean_improvement": self.mean_improvement,
            "exit_improvement": self.exit_improvement,
            "hold_improvement": self.hold_improvement,
            "counter_trend_checkpoints": self.counter_trend_checkpoints,
            "counter_trend_improvement": self.counter_trend_improvement,
            "reasons": list(self.reasons),
            "note": ("The even-hour policy is a hypothesis. NOT_PROVEN is the default "
                     "verdict and a positive mean alone does not overturn it."),
            "timestamp": self.timestamp,
        }


class EvenHourValidator:
    """Records checkpoints and asks whether the policy earned its place."""

    def __init__(self, *, minimum_samples: int | None = None,
                 minimum_effect: float | None = None, repository: Any = None):
        config = load_yaml().get("phase_17", {}).get("even_hour", {})
        self.minimum_samples = int(
            minimum_samples if minimum_samples is not None
            else config.get("minimum_samples", 30))
        # Below this the difference is noise dressed as a result.
        self.minimum_effect = float(
            minimum_effect if minimum_effect is not None
            else config.get("minimum_effect", 0.0001))
        self.repository = repository
        self._records: dict[str, CheckpointRecord] = {}

    def record(self, record: CheckpointRecord) -> CheckpointRecord:
        self._records[record.checkpoint_id] = record
        return record

    def from_verdict(self, verdict: Any, *, checkpoint_id: str, symbol: str,
                     observations: Mapping[str, Any] | None = None,
                     position_state: str | None = None) -> CheckpointRecord:
        """Build a record from a Phase 16 `ExitVerdict` plus the readings around it.

        The exit engine already weighed these inputs; recording them here means
        the validation asks about the same evidence the decision used rather than
        a reconstruction of it.
        """
        payload = verdict.as_dict() if hasattr(verdict, "as_dict") else dict(verdict or {})
        conditions = payload.get("conditions") or {}
        readings = dict(observations or {})
        return self.record(CheckpointRecord(
            checkpoint_id=str(checkpoint_id), symbol=str(symbol).upper(),
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc),
            decision=str(payload.get("action") or ""),
            reason=str(payload.get("exit_reason") or "") or ", ".join(payload.get("reasons") or []),
            trend=readings.get("trend") or conditions.get("regime"),
            liquidity=readings.get("liquidity") or _flag(conditions.get("liquidity_valid")),
            structure=readings.get("structure") or _flag(conditions.get("structure_valid")),
            ichimoku=readings.get("ichimoku"), rsi=_number(readings.get("rsi")),
            adx=_number(readings.get("adx")), nn=_number(payload.get("confidence")),
            strategy=readings.get("strategy"),
            risk=readings.get("risk") or _flag(conditions.get("risk_allowed"), "ALLOWED",
                                               "BLOCKED"),
            position_state=position_state or readings.get("position_state"),
            alignment=payload.get("alignment"),
            required_confidence=payload.get("required_confidence"),
            confidence=payload.get("confidence"),
            context={"at_checkpoint": payload.get("at_checkpoint"),
                     "next_checkpoint": payload.get("next_checkpoint")}))

    def score(self, checkpoint_id: str, *, realized_pnl: float,
              counterfactual_pnl: float) -> CheckpointRecord | None:
        """Attach what happened, and what would have happened had the position held."""
        from dataclasses import replace

        record = self._records.get(str(checkpoint_id))
        if record is None:
            return None
        scored = replace(record, realized_pnl=float(realized_pnl),
                         counterfactual_pnl=float(counterfactual_pnl))
        self._records[scored.checkpoint_id] = scored
        return scored

    @property
    def records(self) -> tuple[CheckpointRecord, ...]:
        return tuple(self._records.values())

    def evaluate(self, records: Sequence[CheckpointRecord] | None = None) -> EvenHourReport:
        """Did the checkpoints improve outcomes? Default answer: not proven."""
        rows = list(records if records is not None else self.records)
        scored = [row for row in rows if row.improvement is not None]
        complete = sum(row.complete for row in rows)
        exits = [row for row in scored if str(row.decision).upper() == "EXIT"]
        holds = [row for row in scored if str(row.decision).upper() == "HOLD"]
        counter = [row for row in scored if str(row.alignment or "").upper() == "COUNTER_TREND"]

        improvements = [row.improvement for row in scored]
        mean = fmean(improvements) if improvements else None

        reasons: list[str] = []
        if len(scored) < self.minimum_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
            verdict = EvenHourVerdict.INSUFFICIENT_DATA
        elif mean is not None and mean < -self.minimum_effect:
            reasons.append("CHECKPOINTS_COST_MORE_THAN_THEY_SAVED")
            verdict = EvenHourVerdict.HARMFUL
        elif mean is not None and mean > self.minimum_effect:
            verdict = EvenHourVerdict.IMPROVES
        else:
            # Positive but inside the noise floor is not an improvement.
            reasons.append("EFFECT_BELOW_MINIMUM")
            verdict = EvenHourVerdict.NOT_PROVEN
        if complete < len(rows):
            reasons.append("INCOMPLETE_CHECKPOINT_OBSERVATIONS")

        return EvenHourReport(
            verdict=verdict, checkpoints=len(rows), complete=complete, scored=len(scored),
            exits=len(exits), holds=len(holds),
            mean_improvement=round(mean, 8) if mean is not None else None,
            exit_improvement=round(fmean([row.improvement for row in exits]), 8) if exits else None,
            hold_improvement=round(fmean([row.improvement for row in holds]), 8) if holds else None,
            counter_trend_checkpoints=len(counter),
            counter_trend_improvement=(round(fmean([row.improvement for row in counter]), 8)
                                       if counter else None),
            reasons=tuple(reasons))


def _flag(value: Any, truthy: str = "VALID", falsy: str = "INVALID") -> str | None:
    if value is None:
        return None
    return truthy if value else falsy


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None
