"""Open-position monitoring (section 23).

MAE and MFE are the two numbers a broker never gives you: they exist only if
something watches the position while it is open. This module keeps that running
record per ticket, alongside the distances that decide whether a stop is about to
be hit and whether the position is still inside its risk budget.

Monitoring is read-only. Nothing here modifies, closes or hedges a position.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    mae: float
    mfe: float
    duration_seconds: float
    spread: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    sl_distance: float | None = None
    tp_distance: float | None = None
    dca_levels: int = 0
    strategy_state: str | None = None
    model_state: str | None = None
    swap: float = 0.0
    commission: float = 0.0
    opened_at: datetime | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket, "symbol": self.symbol, "direction": self.direction,
            "volume": self.volume, "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": round(self.unrealized_pnl, 6),
            "mae": round(self.mae, 8), "mfe": round(self.mfe, 8),
            "duration_seconds": round(self.duration_seconds, 1), "spread": self.spread,
            "stop_loss": self.stop_loss, "take_profit": self.take_profit,
            "sl_distance": None if self.sl_distance is None else round(self.sl_distance, 8),
            "tp_distance": None if self.tp_distance is None else round(self.tp_distance, 8),
            "dca_levels": self.dca_levels, "strategy_state": self.strategy_state,
            "model_state": self.model_state, "swap": self.swap,
            "commission": self.commission, "opened_at": self.opened_at,
            "timestamp": self.timestamp,
        }


class PositionMonitor:
    """Running MAE/MFE per ticket. Excursions are in price terms, never in lots.

    Price terms make the numbers comparable with the observation pipeline, which
    records MAE/MFE the same way for trades that were never executed. That is
    what makes section 32's DEMO-versus-OBSERVATION comparison possible at all.
    """

    def __init__(self):
        self._snapshots: dict[int, PositionSnapshot] = {}

    @staticmethod
    def _sign(direction: Any) -> int:
        return -1 if str(direction).strip().upper() in {"SELL", "SHORT"} else 1

    def update(self, position: Any, *, current_price: float | None = None,
               now: datetime | None = None, spread: float | None = None,
               dca_levels: int | None = None, strategy_state: str | None = None,
               model_state: str | None = None) -> PositionSnapshot:
        """Fold one observation of a position into its running record."""
        read = position.get if isinstance(position, dict) else (
            lambda name, default=None: getattr(position, name, default))
        ticket = int(read("ticket") or 0)
        moment = now or datetime.now(timezone.utc)
        entry = float(read("open_price") or read("entry_price") or 0.0)
        price = float(current_price if current_price is not None
                      else (read("current_price") or entry))
        direction = str(read("direction") or read("side") or "BUY")
        sign = self._sign(direction)
        excursion = (price - entry) * sign

        previous = self._snapshots.get(ticket)
        mfe = max(excursion, previous.mfe if previous else 0.0)
        mae = min(excursion, previous.mae if previous else 0.0)
        opened = read("open_time") or read("opened_at") or (previous.opened_at if previous else None)
        if opened is not None and opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        duration = (moment - opened).total_seconds() if opened else (
            previous.duration_seconds if previous else 0.0)

        stop_loss = read("stop_loss") if read("stop_loss") is not None else read("sl")
        take_profit = read("take_profit") if read("take_profit") is not None else read("tp")
        snapshot = PositionSnapshot(
            ticket=ticket, symbol=str(read("symbol") or ""), direction=direction.upper(),
            volume=float(read("volume") or 0.0), entry_price=entry, current_price=price,
            unrealized_pnl=float(read("profit") if read("profit") is not None
                                 else read("unrealized_pnl") or 0.0),
            mae=mae, mfe=mfe, duration_seconds=max(0.0, duration),
            spread=spread if spread is not None else (previous.spread if previous else None),
            stop_loss=float(stop_loss) if stop_loss else None,
            take_profit=float(take_profit) if take_profit else None,
            sl_distance=abs(price - float(stop_loss)) if stop_loss else None,
            tp_distance=abs(float(take_profit) - price) if take_profit else None,
            dca_levels=int(dca_levels if dca_levels is not None
                           else (previous.dca_levels if previous else 0)),
            strategy_state=strategy_state or (previous.strategy_state if previous else None),
            model_state=model_state or (previous.model_state if previous else None),
            swap=float(read("swap") or 0.0), commission=float(read("commission") or 0.0),
            opened_at=opened, timestamp=moment)
        self._snapshots[ticket] = snapshot
        return snapshot

    def update_all(self, positions: Any, **kwargs: Any) -> tuple[PositionSnapshot, ...]:
        return tuple(self.update(position, **kwargs) for position in positions)

    def get(self, ticket: int) -> PositionSnapshot | None:
        return self._snapshots.get(int(ticket))

    def close(self, ticket: int) -> PositionSnapshot | None:
        """Drop a ticket once it is gone. The final snapshot is returned for the journal."""
        return self._snapshots.pop(int(ticket), None)

    def reconcile_open(self, tickets: Any) -> tuple[PositionSnapshot, ...]:
        """Drop every ticket the broker no longer reports; return what was dropped."""
        live = {int(ticket) for ticket in tickets}
        gone = [ticket for ticket in self._snapshots if ticket not in live]
        return tuple(self._snapshots.pop(ticket) for ticket in gone)

    @property
    def snapshots(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._snapshots.values())

    def summary(self) -> dict[str, Any]:
        rows = self.snapshots
        return {
            "count": len(rows),
            "unrealized_pnl": round(sum(row.unrealized_pnl for row in rows), 6),
            "volume": round(sum(row.volume for row in rows), 6),
            "worst_mae": round(min([row.mae for row in rows], default=0.0), 8),
            "best_mfe": round(max([row.mfe for row in rows], default=0.0), 8),
            "symbols": sorted({row.symbol for row in rows}),
        }
