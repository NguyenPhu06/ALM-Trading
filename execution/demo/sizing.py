"""Position sizing (section 8).

There is no arbitrary lot size anywhere in this phase. A volume is derived from
account equity, the configured risk percentage, the stop distance and the tick
economics of the symbol, then clamped by the broker volume constraints and by
the Phase 16 exposure limits.

The refusal cases matter more than the arithmetic: without a stop distance there
is no defined risk, and without tick economics the risk cannot be converted into
a lot size. Both return volume 0 with a reason rather than a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, isfinite
from typing import Any

from config.settings import load_yaml
from execution.demo.limits import DemoRiskLimits

NO_STOP_DISTANCE = "NO_STOP_DISTANCE"
NO_TICK_ECONOMICS = "NO_TICK_ECONOMICS"
NO_EQUITY = "NO_EQUITY"
INVALID_RISK_PERCENT = "INVALID_RISK_PERCENT"
BELOW_MINIMUM_VOLUME = "BELOW_MINIMUM_VOLUME"
CAPPED_BY_MAX_POSITION_SIZE = "CAPPED_BY_MAX_POSITION_SIZE"
CAPPED_BY_BROKER_MAXIMUM = "CAPPED_BY_BROKER_MAXIMUM"
CAPPED_BY_SYMBOL_EXPOSURE = "CAPPED_BY_SYMBOL_EXPOSURE"
CAPPED_BY_TOTAL_EXPOSURE = "CAPPED_BY_TOTAL_EXPOSURE"
CAPPED_BY_MARGIN = "CAPPED_BY_MARGIN"
RISK_PERCENT_ABOVE_LIMIT = "RISK_PERCENT_CLAMPED_TO_LIMIT"


@dataclass(frozen=True, slots=True)
class SymbolContract:
    """The broker facts sizing needs. Read from MT5 when available, configured otherwise."""

    symbol: str
    tick_size: float = 0.00001
    tick_value: float = 1.0
    contract_size: float = 100_000.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    digits: int = 5
    margin_per_lot: float | None = None

    @property
    def usable(self) -> bool:
        return (self.tick_size > 0 and self.tick_value > 0 and self.volume_step > 0
                and isfinite(self.tick_size) and isfinite(self.tick_value))

    @classmethod
    def from_config(cls, symbol: str, **overrides: Any) -> "SymbolContract":
        config = load_yaml().get("phase_16", {}).get("symbol", {})
        payload = dict(config.get("default", {}) or {})
        payload.update(config.get(symbol.strip().upper(), {}) or {})
        payload.update(overrides)
        allowed = {"tick_size", "tick_value", "contract_size", "volume_min",
                   "volume_max", "volume_step", "digits", "margin_per_lot"}
        return cls(symbol=symbol.strip().upper(),
                   **{key: value for key, value in payload.items() if key in allowed})

    @classmethod
    def from_symbol_info(cls, symbol: str, info: Any, **overrides: Any) -> "SymbolContract":
        """Prefer what the terminal reports; fall back to configuration per field."""
        read = info.get if isinstance(info, dict) else (lambda n, d=None: getattr(info, n, d))
        candidates = {
            "tick_size": read("trade_tick_size") or read("tick_size") or read("point"),
            "tick_value": read("trade_tick_value") or read("tick_value"),
            "contract_size": read("trade_contract_size") or read("contract_size"),
            "volume_min": read("volume_min"), "volume_max": read("volume_max"),
            "volume_step": read("volume_step"), "digits": read("digits"),
        }
        known = {name: value for name, value in candidates.items() if value not in (None, 0)}
        known.update(overrides)
        if "digits" in known:
            known["digits"] = int(known["digits"])
        return cls.from_config(symbol, **known)

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "tick_size": self.tick_size, "tick_value": self.tick_value,
                "contract_size": self.contract_size, "volume_min": self.volume_min,
                "volume_max": self.volume_max, "volume_step": self.volume_step,
                "digits": self.digits, "margin_per_lot": self.margin_per_lot}


@dataclass(frozen=True, slots=True)
class PositionSize:
    symbol: str
    volume: float
    risk_amount: float
    stop_distance: float
    risk_percent: float
    raw_volume: float = 0.0
    notional: float = 0.0
    reasons: tuple[str, ...] = ()
    caps: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.volume > 0

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "volume": self.volume, "risk_amount": self.risk_amount,
                "stop_distance": self.stop_distance, "risk_percent": self.risk_percent,
                "raw_volume": self.raw_volume, "notional": self.notional,
                "valid": self.valid, "reasons": list(self.reasons), "caps": dict(self.caps)}


class PositionSizer:
    """Turns risk into lots, or refuses. It never returns a default lot size."""

    def __init__(self, limits: DemoRiskLimits | None = None):
        self.limits = limits or DemoRiskLimits.from_config()

    @staticmethod
    def _floor_to_step(volume: float, step: float) -> float:
        if step <= 0:
            return volume
        # Round before flooring: 0.03/0.01 is 2.9999999999999996 in binary floats.
        return floor(round(volume / step, 9)) * step

    def calculate(self, *, symbol: str, equity: float, entry_price: float,
                  stop_loss: float | None, contract: SymbolContract | None = None,
                  risk_percent: float | None = None, open_symbol_exposure: float = 0.0,
                  open_total_exposure: float = 0.0, free_margin: float | None = None,
                  margin_per_lot: float | None = None) -> PositionSize:
        contract = contract or SymbolContract.from_config(symbol)
        reasons: list[str] = []
        caps: dict[str, Any] = {}

        requested = self.limits.max_risk_per_trade if risk_percent is None else float(risk_percent)
        if not isfinite(requested) or requested <= 0:
            return PositionSize(symbol.upper(), 0.0, 0.0, 0.0, 0.0, reasons=(INVALID_RISK_PERCENT,))
        if requested > self.limits.max_risk_per_trade:
            # Clamp rather than refuse: the configured hard limit wins over a caller.
            reasons.append(RISK_PERCENT_ABOVE_LIMIT)
            requested = self.limits.max_risk_per_trade

        if not isfinite(float(equity)) or float(equity) <= 0:
            return PositionSize(symbol.upper(), 0.0, 0.0, 0.0, requested, reasons=(NO_EQUITY,))
        if stop_loss is None or not isfinite(float(stop_loss)) or float(stop_loss) <= 0:
            return PositionSize(symbol.upper(), 0.0, 0.0, 0.0, requested,
                                reasons=tuple(reasons + [NO_STOP_DISTANCE]))

        stop_distance = abs(float(entry_price) - float(stop_loss))
        if stop_distance <= 0 or stop_distance < self.limits.min_stop_distance:
            return PositionSize(symbol.upper(), 0.0, 0.0, stop_distance, requested,
                                reasons=tuple(reasons + [NO_STOP_DISTANCE]))
        if not contract.usable:
            return PositionSize(symbol.upper(), 0.0, 0.0, stop_distance, requested,
                                reasons=tuple(reasons + [NO_TICK_ECONOMICS]))

        risk_amount = float(equity) * requested
        ticks = stop_distance / contract.tick_size
        loss_per_lot = ticks * contract.tick_value
        if loss_per_lot <= 0:
            return PositionSize(symbol.upper(), 0.0, risk_amount, stop_distance, requested,
                                reasons=tuple(reasons + [NO_TICK_ECONOMICS]))

        raw = risk_amount / loss_per_lot
        volume = raw
        caps["risk_volume"] = round(raw, 6)

        if volume > self.limits.max_position_size:
            volume = self.limits.max_position_size
            reasons.append(CAPPED_BY_MAX_POSITION_SIZE)
        if volume > contract.volume_max:
            volume = contract.volume_max
            reasons.append(CAPPED_BY_BROKER_MAXIMUM)

        price = float(entry_price)
        notional_per_lot = contract.contract_size * price
        if notional_per_lot > 0:
            symbol_room = self.limits.max_symbol_exposure - float(open_symbol_exposure)
            total_room = self.limits.max_total_exposure - float(open_total_exposure)
            for room, code in ((symbol_room, CAPPED_BY_SYMBOL_EXPOSURE),
                               (total_room, CAPPED_BY_TOTAL_EXPOSURE)):
                allowed = max(0.0, room) / notional_per_lot
                if allowed < volume:
                    volume = allowed
                    reasons.append(code)
            caps["symbol_exposure_room"] = round(symbol_room, 2)
            caps["total_exposure_room"] = round(total_room, 2)

        per_lot_margin = margin_per_lot if margin_per_lot is not None else contract.margin_per_lot
        if free_margin is not None and per_lot_margin:
            budget = max(0.0, float(free_margin)) * self.limits.max_margin_usage
            allowed = budget / float(per_lot_margin)
            caps["margin_volume"] = round(allowed, 6)
            if allowed < volume:
                volume = allowed
                reasons.append(CAPPED_BY_MARGIN)

        volume = self._floor_to_step(volume, contract.volume_step or self.limits.volume_step)
        floor_volume = max(contract.volume_min, self.limits.min_volume)
        if volume < floor_volume:
            # Rounding down below the tradable minimum means the risk budget does
            # not buy one lot. Trading the minimum anyway would exceed the risk.
            return PositionSize(symbol.upper(), 0.0, risk_amount, stop_distance, requested,
                                round(raw, 6), reasons=tuple(reasons + [BELOW_MINIMUM_VOLUME]),
                                caps=caps)

        volume = round(volume, 6)
        return PositionSize(symbol.upper(), volume, round(risk_amount, 6), stop_distance,
                            requested, round(raw, 6), round(volume * notional_per_lot, 2),
                            tuple(reasons), caps)
