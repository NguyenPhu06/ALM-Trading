"""Hard risk limits (sections 9 and 25).

Every limit is configurable and every default is conservative. None of these
numbers was fitted to the test set and none should be: they are a bound on how
wrong the system may be, not a parameter of the strategy.

A limit that cannot be evaluated is treated as breached, never as satisfied.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from config.settings import load_yaml

# Stable codes so alerts, the dashboard and tests key off the same strings.
MAX_RISK_PER_TRADE = "MAX_RISK_PER_TRADE_EXCEEDED"
MAX_DAILY_LOSS = "MAX_DAILY_LOSS_EXCEEDED"
MAX_TOTAL_DRAWDOWN = "MAX_TOTAL_DRAWDOWN_EXCEEDED"
MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS_REACHED"
MAX_SYMBOL_EXPOSURE = "MAX_SYMBOL_EXPOSURE_EXCEEDED"
MAX_TOTAL_EXPOSURE = "MAX_TOTAL_EXPOSURE_EXCEEDED"
MAX_DCA_LEVELS = "MAX_DCA_LEVELS_REACHED"
MAX_DCA_EXPOSURE = "MAX_TOTAL_DCA_EXPOSURE_EXCEEDED"
MAX_TRADES_PER_DAY = "MAX_TRADES_PER_DAY_REACHED"
MAX_SPREAD = "MAX_SPREAD_EXCEEDED"
MAX_SLIPPAGE = "MAX_SLIPPAGE_EXCEEDED"
MAX_MARGIN_USAGE = "MAX_MARGIN_USAGE_EXCEEDED"
MAX_POSITION_SIZE = "MAX_POSITION_SIZE_EXCEEDED"


@dataclass(frozen=True, slots=True)
class DemoRiskLimits:
    max_risk_per_trade: float = 0.005
    max_daily_loss: float = 0.02
    max_total_drawdown: float = 0.05
    max_open_positions: int = 2
    max_symbol_exposure: float = 5000.0
    max_total_exposure: float = 10000.0
    max_dca_levels: int = 2
    max_total_dca_exposure: float = 7500.0
    max_trades_per_day: int = 5
    max_spread: float = 0.0005
    max_slippage: float = 0.0003
    max_margin_usage: float = 0.30
    max_position_size: float = 0.05
    min_volume: float = 0.01
    volume_step: float = 0.01
    min_stop_distance: float = 0.0005

    @classmethod
    def from_config(cls, overrides: dict[str, Any] | None = None) -> "DemoRiskLimits":
        config = dict(load_yaml().get("phase_16", {}).get("limits", {}))
        config.update(overrides or {})
        known = {field.name: field.type for field in fields(cls)}
        payload: dict[str, Any] = {}
        for name, value in config.items():
            if name not in known:
                continue
            payload[name] = int(value) if known[name] == "int" else float(value)
        return cls(**payload)

    def as_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}
