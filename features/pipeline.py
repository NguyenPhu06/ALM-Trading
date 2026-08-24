from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from config.settings import load_yaml
from data_quality import MarketDataValidator
from database.repositories import CandleRepository, LiquidityEventRepository, StructureEventRepository
from features.liquidity import LiquidityEngine
from features.candles import candle_close_time, closed_candle_prefix, utc_aware
from features.mtf import MTFAlignmentEngine
from data_sources.resampler import MarketDataResampler
from features.session import SessionEngine
from features.snapshot import create_feature_snapshot
from features.structure import MarketStructureEngine
from features.regime import MarketRegimeSnapshot
from features.regime.service import MarketRegimeService


logger = logging.getLogger(__name__)


class Phase1BPipeline:
    """Calculate and persist Phase 1B features exclusively from stored candles."""

    def __init__(self, session: Session):
        self.session = session
        config = load_yaml()
        engine_config = config.get("phase_1b", {})
        session_config = config.get("sessions", {})
        session_engine = SessionEngine(
            timezone=session_config.get("timezone", "UTC"),
            asia=tuple(session_config.get("asia", ("00:00", "09:00"))),
            london=tuple(session_config.get("london", ("07:00", "16:00"))),
            new_york=tuple(session_config.get("new_york", ("13:00", "22:00"))),
        )
        right_bars = int(engine_config.get("swing_right_bars", 2))
        if right_bars != 2:
            raise ValueError("Phase 1B.1 requires swing_right_bars=2")
        common: dict[str, Any] = {
            "swing_left_bars": int(engine_config.get("swing_left_bars", 2)),
            "swing_right_bars": right_bars,
            "equal_level_tolerance_points": float(engine_config.get("equal_level_tolerance_points", 3)),
            "point_size": engine_config.get("point_size", 0.00001),
        }
        self.structure_engine = MarketStructureEngine(
            **common, break_mode=engine_config.get("break_mode", "CLOSE_BREAK"),
        )
        self.liquidity_engine = LiquidityEngine(
            **common,
            minimum_rejection_ratio=float(engine_config.get("minimum_rejection_ratio", 0.15)),
            session_engine=session_engine,
        )
        self.session_engine = session_engine
        self.resampler = MarketDataResampler()
        self.alignment_engine = MTFAlignmentEngine()
        self.last_snapshots: list[dict[str, Any]] = []
        self.last_regime: MarketRegimeSnapshot | None = None

    def run(
        self, symbol: str, timeframe: str, *,
        start: datetime | None = None, end: datetime | None = None,
    ) -> dict[str, int]:
        database_candles = CandleRepository(self.session).chronological(
            symbol=symbol.upper(), timeframe=timeframe.upper(), start=start, end=end,
        )
        candles = closed_candle_prefix(database_candles)
        if end is not None:
            candles = [candle for candle in candles if candle_close_time(candle) <= utc_aware(end)]
        candle_dicts = [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in candles]
        gaps = MarketDataValidator().detect_gaps(candle_dicts)
        if gaps:
            logger.warning("data gap: symbol=%s timeframe=%s count=%d", symbol, timeframe, len(gaps))

        # Required causal order: closed filter -> swings/structure/BOS/CHoCH ->
        # liquidity/sweeps -> MTF alignment -> snapshots.
        structure = self.structure_engine.calculate(candles)
        liquidity = self.liquidity_engine.calculate(candles)
        all_structure = list(structure)
        all_liquidity = list(liquidity)
        events_by_timeframe = {timeframe.upper(): list(structure)}
        resampled_counts: dict[str, int] = {}
        if timeframe.upper() == "M15":
            source_rows: dict[str, list[Any]] = {"M15": list(candles)}
            as_of = candle_close_time(candles[-1]) if candles else None
            for source_timeframe, target in (("M15", "H1"), ("H1", "H4"), ("H4", "D1")):
                native = closed_candle_prefix(CandleRepository(self.session).chronological(
                    symbol=symbol.upper(), timeframe=target, start=start, end=end,
                ))
                if as_of is not None:
                    native = [candle for candle in native if candle_close_time(candle) <= as_of]
                target_candles = native or self.resampler.resample(
                    source_rows[source_timeframe], source_timeframe, target, as_of=as_of,
                )
                source_rows[target] = list(target_candles)
                resampled_counts[target] = 0 if native else len(target_candles)
                target_structure = self.structure_engine.calculate(target_candles)
                target_liquidity = self.liquidity_engine.calculate(target_candles)
                events_by_timeframe[target] = target_structure
                all_structure.extend(target_structure)
                all_liquidity.extend(target_liquidity)
            alignments = self.alignment_engine.align(candles, events_by_timeframe)
        else:
            alignments = []
        self.last_snapshots = [
            create_feature_snapshot(
                candle, structure, liquidity,
                session_engine=self.session_engine,
                mtf_alignment=alignment if alignments else None,
            )
            for candle, alignment in zip(candles, alignments)
        ] if alignments else [
            create_feature_snapshot(candle, structure, liquidity, session_engine=self.session_engine)
            for candle in candles
        ]
        structure_rows = [{
            "event_timestamp": event.event_timestamp,
            "confirmation_timestamp": event.confirmation_timestamp,
            "symbol": event.symbol,
            "timeframe": event.timeframe,
            "event_type": event.event_type,
            "direction": event.direction,
            "price": event.price,
            "strength": event.strength,
            "metadata_json": event.metadata,
            "source": "phase_1b_structure",
        } for event in all_structure]
        liquidity_rows = [{
            "event_timestamp": event.event_timestamp,
            "confirmation_timestamp": event.confirmation_timestamp,
            "symbol": event.symbol,
            "timeframe": event.timeframe,
            "event_type": event.event_type,
            "direction": event.direction,
            "price": event.price,
            "strength": event.strength,
            "metadata_json": event.metadata,
            "source": "phase_1b_liquidity",
        } for event in all_liquidity]
        result = {
            "candles": len(database_candles),
            "closed_candles": len(candles),
            "open_candles_excluded": len(database_candles) - len(candles),
            "structure_events_inserted": StructureEventRepository(self.session).add_many(structure_rows),
            "liquidity_events_inserted": LiquidityEventRepository(self.session).add_many(liquidity_rows),
            "mtf_candles": sum(resampled_counts.values()),
            "mtf_snapshots": len(self.last_snapshots),
            "gaps": len(gaps),
        }
        if timeframe.upper() == "M15" and candles:
            self.last_regime = MarketRegimeService(self.session).calculate(symbol, as_of=candle_close_time(candles[-1]))
            result["regime_calculated"] = 1
        else:
            self.last_regime = None
            result["regime_calculated"] = 0
        return result
