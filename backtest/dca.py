from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backtest.contracts import SimulatedTrade, TradeDirection


@dataclass(frozen=True, slots=True)
class DCAConfig:
    maximum_entries: int = 3
    maximum_exposure: float = 3.0
    distance_between_entries: float = 0.001
    maximum_drawdown: float = 0.02
    time_based_exit: timedelta = timedelta(hours=8)

    def __post_init__(self) -> None:
        if self.maximum_entries < 1 or self.maximum_exposure <= 0 or self.distance_between_entries <= 0:
            raise ValueError("invalid DCA limits")
        if not 0 < self.maximum_drawdown < 1:
            raise ValueError("maximum_drawdown must be between zero and one")


@dataclass(slots=True)
class SimulatedPosition:
    entry_time: datetime
    direction: TradeDirection
    entries: list[dict]
    maximum_drawdown_seen: float = 0.0
    evaluations: list[dict] = field(default_factory=list)
    counter_trend_trade: bool = False
    closed: bool = False

    @property
    def exposure(self) -> float:
        return sum(float(entry["size"]) for entry in self.entries)

    @property
    def average_price(self) -> float:
        return sum(float(entry["price"]) * float(entry["size"]) for entry in self.entries) / self.exposure


class DCASimulator:
    """Constrained position simulation, never an order execution mechanism."""

    def __init__(self, config: DCAConfig | None = None):
        self.config = config or DCAConfig()

    def open(
        self, *, timestamp: datetime, price: float, direction: TradeDirection,
        size: float, higher_timeframe_bias: str, reason: str,
    ) -> SimulatedPosition:
        if size <= 0 or size > self.config.maximum_exposure:
            raise ValueError("initial size exceeds DCA exposure limits")
        counter = (direction is TradeDirection.LONG and "BEARISH" in higher_timeframe_bias) or (
            direction is TradeDirection.SHORT and "BULLISH" in higher_timeframe_bias
        )
        return SimulatedPosition(
            timestamp, direction, [{"timestamp": timestamp, "price": price, "size": size, "reason": reason}],
            counter_trend_trade=counter,
        )

    def consider_entry(
        self, position: SimulatedPosition, *, timestamp: datetime, price: float,
        size: float, reason: str,
    ) -> bool:
        if position.closed or len(position.entries) >= self.config.maximum_entries:
            return False
        if size <= 0 or position.exposure + size > self.config.maximum_exposure:
            return False
        if self.drawdown_fraction(position, price) >= self.config.maximum_drawdown:
            return False
        last_price = float(position.entries[-1]["price"])
        adverse_distance = last_price - price if position.direction is TradeDirection.LONG else price - last_price
        if adverse_distance < self.config.distance_between_entries:
            return False
        position.entries.append({"timestamp": timestamp, "price": price, "size": size, "reason": reason})
        return True

    @staticmethod
    def pnl(position: SimulatedPosition, price: float) -> float:
        sign = 1.0 if position.direction is TradeDirection.LONG else -1.0
        return round(sign * (price - position.average_price) * position.exposure, 10)

    @staticmethod
    def drawdown_fraction(position: SimulatedPosition, price: float) -> float:
        adverse = max(0.0, position.average_price - price) if position.direction is TradeDirection.LONG else max(0.0, price - position.average_price)
        return adverse / position.average_price if position.average_price else 0.0

    def mark(self, position: SimulatedPosition, *, timestamp: datetime, price: float, reason: str) -> None:
        drawdown = self.drawdown_fraction(position, price)
        position.maximum_drawdown_seen = max(position.maximum_drawdown_seen, drawdown)
        position.evaluations.append({
            "timestamp": timestamp, "price": price, "pnl": self.pnl(position, price),
            "drawdown": drawdown, "reason": reason,
        })

    def close(self, position: SimulatedPosition, *, timestamp: datetime, price: float, reason: str) -> SimulatedTrade:
        self.mark(position, timestamp=timestamp, price=price, reason=reason)
        position.closed = True
        return SimulatedTrade(
            position.entry_time, float(position.entries[0]["price"]), timestamp, price,
            position.direction, position.exposure, self.pnl(position, price),
            position.maximum_drawdown_seen, reason, position.counter_trend_trade,
            tuple(position.entries), tuple(position.evaluations),
        )
