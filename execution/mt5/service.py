"""Read-only MT5 service: connect, read, validate, persist, reconcile.

This is the only place that joins the MT5 client to the ALM database. Every write
it performs is an observation record. It never creates, modifies or closes a
trade — on either side.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from config.settings import load_yaml
from data_sources.validators import QualityStatus
from database.repositories.mt5 import DEFAULT_ACCOUNT_ID, MT5Repository
from execution.mt5.client import MT5ReadOnlyClient, ReadResult
from execution.mt5.connection import ConnectionReport, ConnectionState
from execution.mt5.quality import MT5DataQualityGate, QualityOutcome, compare_sources
from execution.mt5.symbols import SymbolInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    symbol: str
    timeframes: dict[str, int] = field(default_factory=dict)
    quality: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tick: dict[str, Any] | None = None
    code: str = "OK"

    @property
    def ok(self) -> bool:
        return self.code == "OK"


class MT5ReadOnlyService:
    def __init__(self, session, *, client: MT5ReadOnlyClient | None = None,
                 repository: MT5Repository | None = None,
                 gate: MT5DataQualityGate | None = None,
                 account_id: str = DEFAULT_ACCOUNT_ID):
        config = load_yaml().get("phase_10", {})
        self.session = session
        self.client = client or MT5ReadOnlyClient()
        self.repository = repository or MT5Repository(session)
        self.account_id = account_id
        self.timeframes = tuple(config.get("timeframes") or ("D1", "H4", "H1", "M30", "M15", "M5"))
        self.default_count = int(config.get("default_candle_count", 500))
        comparison = config.get("source_comparison", {})
        self.price_tolerance = float(comparison.get("price_tolerance", 0.0010))
        self.timestamp_tolerance = float(comparison.get("timestamp_tolerance_seconds", 120))
        self.gate = gate or MT5DataQualityGate(
            tick_stale_seconds=float(config.get("tick_stale_seconds", 30)),
            known_symbols=tuple(config.get("canonical_symbols") or ()),
        )

    # ------------------------------------------------------------------ lifecycle
    def connect(self) -> ConnectionReport:
        report = self.client.connect()
        self.repository.save_connection_event(report)
        if report.state is ConnectionState.CONNECTED:
            self.sync_account()
        return report

    def disconnect(self) -> ConnectionReport:
        report = self.client.disconnect()
        self.repository.save_connection_event(report)
        return report

    # -------------------------------------------------------------------- reads
    def sync_account(self) -> ReadResult:
        result = self.client.get_account()
        if not result.ok:
            return result
        self.repository.upsert_account(result.data, account_id=self.account_id)
        self.repository.save_account_snapshot(result.data, account_id=self.account_id)
        return result

    def sync_symbols(self) -> ReadResult:
        result = self.client.get_symbols(refresh=True)
        if not result.ok:
            return result
        resolver = self.client.resolver
        resolved: list[SymbolInfo] = []
        for canonical in (self.client.canonical_symbols or ()):
            info, code, _ = resolver.try_resolve(canonical) if resolver else (None, "NO_RESOLVER", ())
            if info is not None:
                resolved.append(info)
        self.repository.save_symbol_snapshots(resolved or result.data)
        return ReadResult(True, tuple(resolved or result.data))

    def sync_tick(self, symbol: str) -> ReadResult:
        result = self.client.get_tick(symbol)
        if not result.ok:
            return result
        outcome = self.gate.evaluate_tick(result.data, as_of=self.client.now())
        if not outcome.valid:
            self._record_quality(symbol, None, outcome)
            return ReadResult(False, None, outcome.code, outcome.reasons)
        broker = None
        if self.client.resolver:
            info, _, _ = self.client.resolver.try_resolve(symbol)
            broker = info.name if info else None
        self.repository.save_tick(result.data, broker_symbol=broker)
        return result

    def sync_positions(self) -> ReadResult:
        result = self.client.get_positions()
        if result.ok:
            self.repository.save_positions(result.data)
        return result

    def sync_orders(self) -> ReadResult:
        result = self.client.get_orders()
        if result.ok:
            self.repository.save_orders(result.data)
        return result

    # -------------------------------------------------------------- market data
    def _record_quality(self, symbol: str, timeframe: str | None, outcome: QualityOutcome) -> None:
        report = outcome.report
        if report is None:
            from data_sources.validators import DataQualityReport

            report = DataQualityReport(
                datetime.now(timezone.utc), symbol, timeframe or "TICK", 0, 0, 0, 0, 0, 0,
                outcome.status, outcome.reasons, "mt5",
            )
        self.repository.save_data_quality_event(report)

    def sync_market_data(self, symbol: str, *, timeframes: Sequence[str] | None = None,
                         count: int | None = None) -> SyncOutcome:
        """Read D1 through M5, validate each, and persist a quality event per timeframe.

        A timeframe that fails the gate contributes no candles: invalid data is
        never handed on to the feature or strategy layers.
        """
        wanted = tuple(timeframes or self.timeframes)
        counts: dict[str, int] = {}
        statuses: dict[str, str] = {}
        reasons: dict[str, tuple[str, ...]] = {}
        for timeframe in wanted:
            result = self.client.get_rates(symbol, timeframe, count or self.default_count)
            if not result.ok:
                counts[timeframe] = 0
                statuses[timeframe] = "UNAVAILABLE"
                reasons[timeframe] = result.reasons
                continue
            outcome = self.gate.evaluate_candles(result.data, symbol=symbol, timeframe=timeframe,
                                                 as_of=self.client.now())
            self._record_quality(symbol, timeframe, outcome)
            counts[timeframe] = len(outcome.accepted)
            statuses[timeframe] = str(outcome.status)
            reasons[timeframe] = outcome.reasons
        code = "OK" if any(counts.values()) else "NO_MARKET_DATA"
        return SyncOutcome(symbol.upper(), counts, statuses, reasons, code=code)

    def multi_timeframe(self, symbol: str, *, count: int | None = None) -> dict[str, Any]:
        """D1 → M5 payload for the dashboard, each timeframe carrying its own age."""
        now = self.client.now()
        payload: dict[str, Any] = {}
        for timeframe in self.timeframes:
            result = self.client.get_rates(symbol, timeframe, count or 200)
            if not result.ok or not result.data:
                payload[timeframe] = {"available": False, "code": result.code, "source": "mt5"}
                continue
            last = result.data[-1]
            payload[timeframe] = {
                "available": True, "source": "mt5", "count": len(result.data),
                "last_candle": last["timestamp"],
                "data_age_seconds": max(0.0, (now - last["timestamp"]).total_seconds()),
                "open": float(last["open"]), "high": float(last["high"]),
                "low": float(last["low"]), "close": float(last["close"]),
            }
        return payload

    # ----------------------------------------------------------- reconciliation
    def reconcile(self, paper_account: Any | None = None) -> dict[str, Any]:
        """Compare the MT5 DEMO account with ALM's paper account. READ ONLY.

        The two are independent by design in Phase 10 — MT5 is a data provider and
        the paper engine holds its own simulated book — so a difference is
        expected and is reported, never corrected.
        """
        account = self.client.account
        snapshot = self.repository.latest_account_snapshot(self.account_id)
        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc),
            "mt5": account.as_public_dict() if account else None,
            "mt5_snapshot": {
                "timestamp": snapshot.timestamp, "balance": snapshot.balance,
                "equity": snapshot.equity, "environment": snapshot.environment,
            } if snapshot else None,
            "paper": None,
            "differences": {},
            "note": "MT5 and paper books are independent in Phase 10; differences are informational.",
        }
        if paper_account is not None:
            result["paper"] = {
                "balance": paper_account.balance, "equity": paper_account.equity,
                "realized_pnl": paper_account.realized_pnl,
            }
            if account is not None:
                result["differences"] = {
                    "balance": round(account.balance - paper_account.balance, 8),
                    "equity": round(account.equity - paper_account.equity, 8),
                }
        return result

    def compare_with_provider(self, symbol: str, other_quote: dict[str, Any] | None, *,
                              other_source: str = "provider") -> dict[str, Any]:
        tick = self.client.get_tick(symbol)
        comparison = compare_sources(
            tick.data if tick.ok else None, other_quote, symbol=symbol.upper(),
            price_tolerance=self.price_tolerance,
            timestamp_tolerance_seconds=self.timestamp_tolerance,
            other_source=other_source,
        )
        if comparison.discrepancy:
            logger.warning("DATA_SOURCE_DISCREPANCY for %s: %s", symbol, ", ".join(comparison.reasons))
        return comparison.as_dict()

    # ---------------------------------------------------------------- dashboard
    def status(self, *, database_online: bool | None = None) -> dict[str, Any]:
        health = self.client.health_check(database_online=database_online)
        return {
            **self.client.identity(),
            "health": str(health.state),
            "components": [component.as_dict() for component in health.components],
            "timeframes": list(self.timeframes),
            "source": "mt5",
        }
