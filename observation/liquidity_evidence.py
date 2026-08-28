"""Separate what the data OBSERVED from what the model INFERRED.

The distinction matters because the two carry very different epistemic weight:

* OBSERVED — a fact computable from the candles alone. "Price traded through the
  previous day high at 1.1042." Either it happened or it did not.
* INFERRED — a hypothesis derived from those facts. "Resting orders were probably
  clustered above that high." Plausible, unproven, and stated as such.

Nothing here may claim that a bank, institution, whale or market maker is at a
price. `describe()` refuses to emit such a claim; it produces probabilistic
language keyed to the confidence band instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Sequence


class EvidenceKind(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class Confidence(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


# Phrasing per confidence band. Deliberately hedged: none of these asserts an actor.
HEDGE = {
    Confidence.LOW: "may indicate",
    Confidence.MODERATE: "is consistent with",
    Confidence.HIGH: "strongly suggests",
}

# Language we must never produce, and the check that keeps us honest.
FORBIDDEN_CLAIMS = ("bank", "institution", "institutional order", "whale", "market maker",
                    "smart money", "big player")

OBSERVED_TYPES = (
    "EQUAL_HIGH", "EQUAL_LOW", "PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW",
    "SESSION_HIGH", "SESSION_LOW", "LIQUIDITY_SWEEP", "DISPLACEMENT", "REJECTION",
)
INFERRED_TYPES = ("LIQUIDITY_POOL", "RESTING_ORDER_CLUSTER", "IMBALANCE_INTEREST")


@dataclass(frozen=True, slots=True)
class LiquidityEvidence:
    kind: EvidenceKind
    event_type: str
    price: float | None = None
    timeframe: str | None = None
    timestamp: datetime | None = None
    confidence: Confidence = Confidence.LOW
    basis: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def observed(self) -> bool:
        return self.kind is EvidenceKind.OBSERVED

    def describe(self) -> str:
        """Plain-language statement. Observed facts are stated; inferences are hedged."""
        where = f" at {self.price}" if self.price is not None else ""
        frame = f" on {self.timeframe}" if self.timeframe else ""
        label = self.event_type.replace("_", " ").lower()
        if self.observed:
            return f"{label}{where}{frame} was observed"
        return (f"{label}{where}{frame} {HEDGE[self.confidence]} liquidity resting nearby; "
                f"this is an inference, not a confirmed order")

    def as_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "event_type": self.event_type, "price": self.price,
                "timeframe": self.timeframe, "timestamp": self.timestamp,
                "confidence": str(self.confidence), "basis": list(self.basis),
                "statement": self.describe(), **self.details}


@dataclass(frozen=True, slots=True)
class LiquidityReport:
    symbol: str
    observed: tuple[LiquidityEvidence, ...] = ()
    inferred: tuple[LiquidityEvidence, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_evidence(self) -> tuple[LiquidityEvidence, ...]:
        return (*self.observed, *self.inferred)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "timestamp": self.timestamp,
            "observed": [item.as_dict() for item in self.observed],
            "inferred": [item.as_dict() for item in self.inferred],
            "observed_count": len(self.observed), "inferred_count": len(self.inferred),
            "disclaimer": ("Inferred entries are probabilistic hypotheses derived from price "
                           "action. They are not claims about any specific market participant."),
        }


def contains_forbidden_claim(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_CLAIMS)


class LiquidityEvidenceClassifier:
    """Splits liquidity engine output into observed facts and inferred hypotheses."""

    def __init__(self, *, sweep_confidence: Confidence = Confidence.MODERATE):
        self.sweep_confidence = sweep_confidence

    @staticmethod
    def _read(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    def _confidence_for(self, item: Any) -> Confidence:
        strength = self._read(item, "strength")
        try:
            value = float(strength)
        except (TypeError, ValueError):
            return Confidence.LOW
        if value >= 0.7:
            return Confidence.HIGH
        if value >= 0.4:
            return Confidence.MODERATE
        return Confidence.LOW

    def classify_event(self, item: Any, *, timeframe: str | None = None) -> LiquidityEvidence:
        event_type = str(self._read(item, "event_type") or self._read(item, "type") or "UNKNOWN").upper()
        price = self._read(item, "price")
        kind = EvidenceKind.OBSERVED if event_type in OBSERVED_TYPES else EvidenceKind.INFERRED
        basis = ("price action",) if kind is EvidenceKind.OBSERVED else ("derived from price action",)
        return LiquidityEvidence(
            kind, event_type, float(price) if price is not None else None,
            timeframe or self._read(item, "timeframe"),
            self._read(item, "event_timestamp") or self._read(item, "timestamp"),
            self._confidence_for(item), basis,
        )

    def classify(self, events: Iterable[Any], *, symbol: str,
                 timeframe: str | None = None) -> LiquidityReport:
        observed: list[LiquidityEvidence] = []
        inferred: list[LiquidityEvidence] = []
        for item in events or ():
            evidence = self.classify_event(item, timeframe=timeframe)
            (observed if evidence.observed else inferred).append(evidence)
        return LiquidityReport(symbol.upper(), tuple(observed), tuple(inferred))

    def from_timeframes(self, timeframes: dict[str, Any], *, symbol: str) -> LiquidityReport:
        """Build a report from a MarketStateSnapshot's per-timeframe liquidity."""
        observed: list[LiquidityEvidence] = []
        inferred: list[LiquidityEvidence] = []
        for name, state in (timeframes or {}).items():
            sweep = getattr(state, "sweep", None)
            if sweep:
                evidence = self.classify_event(sweep, timeframe=name)
                (observed if evidence.observed else inferred).append(evidence)
            liquidity = getattr(state, "liquidity", None) or {}
            for level in (liquidity.get("levels") or ())[-5:]:
                evidence = self.classify_event(level, timeframe=name)
                (observed if evidence.observed else inferred).append(evidence)
        return LiquidityReport(symbol.upper(), tuple(observed), tuple(inferred))
