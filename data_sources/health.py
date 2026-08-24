from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import get_settings, load_yaml
from data_quality import calculate_freshness, detect_market_data_gaps
from database.models import MarketDataIngestion
from database.repositories import CandleRepository


class MarketDataHealthService:
    """Bounded database health checks; never downloads provider data."""

    def __init__(self, session: Session):
        self.session = session
        config = load_yaml().get("market_data", {})
        self.symbols = tuple(config.get("symbols", ()))
        self.timeframes = tuple(config.get("timeframes", ()))
        self.thresholds = config.get("freshness_threshold_seconds", {})
        self.recent_limit = int(config.get("readiness_recent_candles", 5000))
        self.sample_sources = tuple(config.get("sample_sources", ("local_csv",)))

    def health(self, symbol: str, timeframe: str, *, now: datetime | None = None) -> dict[str, Any]:
        symbol, timeframe = symbol.upper(), timeframe.upper()
        repository = CandleRepository(self.session)
        latest = repository.latest(symbol, timeframe, exclude_sources=self.sample_sources)
        freshness = calculate_freshness(
            symbol, timeframe, latest,
            threshold_seconds=float(self.thresholds.get(timeframe, 0)), now=now,
        )
        timestamps = repository.recent_timestamps(
            symbol, timeframe, exclude_sources=self.sample_sources, limit=self.recent_limit,
        )
        candles = [{"symbol": symbol, "timeframe": timeframe, "timestamp": item} for item in timestamps]
        gaps = detect_market_data_gaps(candles)
        material_gaps = [gap for gap in gaps if gap.expected_candles > 0]
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": repository.count(symbol=symbol, timeframe=timeframe, exclude_sources=self.sample_sources),
            "latest_timestamp": freshness.last_candle_timestamp,
            "status": (
                "MISSING" if freshness.status.value == "MISSING" else
                "HEALTHY" if freshness.status.value == "FRESH" and not material_gaps else
                "STALE" if freshness.status.value == "STALE" else "GAPS"
            ),
            "freshness": asdict(freshness),
            "gaps": len(material_gaps),
            "gap_details": [asdict(gap) for gap in material_gaps],
        }

    def readiness(self, *, now: datetime | None = None) -> dict[str, Any]:
        generated_at = now or datetime.now(timezone.utc)
        symbols: dict[str, dict[str, Any]] = {}
        for symbol in self.symbols:
            symbols[symbol] = {}
            for timeframe in self.timeframes:
                report = self.health(symbol, timeframe, now=generated_at)
                freshness = report["freshness"]["status"]
                if not report["count"]:
                    status = "MISSING"
                elif freshness == "FRESH" and not report["gaps"]:
                    status = "READY"
                else:
                    status = "PARTIAL"
                symbols[symbol][timeframe] = {
                    "status": status,
                    "count": report["count"],
                    "freshness": freshness,
                    "gaps": report["gaps"],
                    "duplicate_candles": 0,
                    "invalid_candles": 0,
                }
        return {"generated_at": generated_at, "symbols": symbols}

    def providers(self) -> list[dict[str, Any]]:
        rows = list(self.session.scalars(
            select(MarketDataIngestion)
            .order_by(MarketDataIngestion.request_end.desc())
            .limit(1000)
        ))
        latest: dict[str, MarketDataIngestion] = {}
        last_success: dict[str, datetime] = {}
        for row in rows:
            latest.setdefault(row.provider, row)
            if row.status.startswith("SUCCESS") and row.provider not in last_success:
                last_success[row.provider] = row.request_end
        configured = load_yaml().get("market_data", {})
        settings = get_settings()
        canonical_provider = "twelve_data" if settings.market_data_provider in {"historical", "twelve_data", "twelvedata"} else settings.market_data_provider
        known = {canonical_provider, *latest}
        result = []
        for provider in sorted(known):
            row = latest.get(provider)
            configured_provider = provider != canonical_provider or bool(settings.market_data_api_key)
            result.append({
                "provider": provider,
                "status": (
                    "UNCONFIGURED" if not configured_provider else
                    "DEGRADED" if row is None else
                    "HEALTHY" if row.status.startswith("SUCCESS") else "ERROR"
                ),
                "last_success": last_success.get(provider),
                "last_error": row.last_error if row and not row.status.startswith("SUCCESS") else None,
                "latency": row.duration_seconds if row else None,
                "supported_symbols": configured.get("symbols", []),
                "supported_timeframes": configured.get("timeframes", []),
            })
        return result
