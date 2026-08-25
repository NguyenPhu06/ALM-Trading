from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Mapping, Sequence

from ai.features import HistoricalFeatureSchema
from ai.labels import MultiHorizonLabel, MultiHorizonLabeler
from data_quality import DataQualityReport, HistoricalDataQualityEngine, MarketDataValidator
from data_sources.resampler import MarketDataResampler
from features.candles import candle_close_time, candle_value, utc_aware
from features.intelligence import MarketIntelligenceEngine
from ai.datasets.split import ChronologicalSplit, ChronologicalSplitter, ScalerState, TrainOnlyStandardizer


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    dataset_id: str
    created_at: datetime
    symbol: str
    timeframes: tuple[str, ...]
    base_timeframe: str
    feature_version: str
    label_version: str
    data_start: datetime
    data_end: datetime
    row_count: int
    feature_count: int
    label_count: int
    schema_hash: str
    dataset_hash: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True, slots=True)
class DatasetSample:
    timestamp: datetime
    symbol: str
    features: dict[str, float]
    normalized_features: dict[str, float]
    label: MultiHorizonLabel
    split: str


@dataclass(frozen=True, slots=True)
class MLDatasetArtifact:
    metadata: DatasetMetadata
    samples: tuple[DatasetSample, ...]
    scaler: ScalerState
    split: ChronologicalSplit
    quality_reports: dict[str, DataQualityReport]
    statistics: dict[str, Any]


class HistoricalDatasetBuilder:
    TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")
    MINIMUM_INDICATOR_HISTORY = 53

    def __init__(
        self, *, classification_threshold: float = 0.0005, outcome_threshold: float | None = None,
        train_ratio: float = 0.70, validation_ratio: float = 0.15,
        require_complete_timeframes: bool = True,
    ):
        self.labeler = MultiHorizonLabeler(
            classification_threshold=classification_threshold, outcome_threshold=outcome_threshold,
        )
        self.splitter = ChronologicalSplitter(train_ratio=train_ratio, validation_ratio=validation_ratio)
        self.require_complete_timeframes = require_complete_timeframes
        self.quality = HistoricalDataQualityEngine()
        self.validator = MarketDataValidator()
        self.resampler = MarketDataResampler()
        self.engine = MarketIntelligenceEngine()

    def build(self, symbol: str, candles_by_timeframe: Mapping[str, Sequence[Any]]) -> MLDatasetArtifact:
        symbol = symbol.upper()
        quality_reports = {
            timeframe: self.quality.inspect(candles_by_timeframe.get(timeframe, ()), symbol=symbol, timeframe=timeframe)
            for timeframe in self.TIMEFRAMES
        }
        prepared = {
            timeframe: self._prepare(candles_by_timeframe.get(timeframe, ()), symbol, timeframe)
            for timeframe in self.TIMEFRAMES
        }
        self._resample_missing(prepared)
        base = prepared["M15"]
        if len(base) <= max(self.labeler.HORIZONS) + 2:
            raise ValueError("insufficient closed M15 candles for Phase 4 labels and chronological split")
        labels = {label.timestamp: label for label in self.labeler.generate(base)}
        close_times = {
            timeframe: [candle_close_time(row) for row in rows]
            for timeframe, rows in prepared.items()
        }
        raw: list[tuple[datetime, dict[str, float], MultiHorizonLabel]] = []
        for candle in base:
            timestamp = candle_close_time(candle)
            label = labels.get(timestamp)
            if label is None:
                continue
            if self.require_complete_timeframes and any(
                bisect_right(close_times[timeframe], timestamp) < self.MINIMUM_INDICATOR_HISTORY
                for timeframe in self.TIMEFRAMES
            ):
                continue
            snapshot = self.engine.calculate(symbol, prepared, as_of=timestamp)
            selected = [snapshot.timeframes[timeframe] for timeframe in self.TIMEFRAMES]
            if self.require_complete_timeframes and (
                not all(state.available for state in selected)
                or any(state.indicators.get("missing_reason") for state in selected)
            ):
                continue
            if any(state.timestamp is not None and state.timestamp > timestamp for state in selected):
                raise RuntimeError("future timeframe state entered feature snapshot")
            features = HistoricalFeatureSchema.extract(snapshot)
            if not all(math.isfinite(value) for value in features.values()):
                raise ValueError("feature vector contains non-finite values")
            raw.append((timestamp, features, label))
        if len(raw) < 3:
            raise ValueError("insufficient causally complete samples for chronological split")

        timestamps = [item[0] for item in raw]
        split = self.splitter.split(timestamps)
        standardizer = TrainOnlyStandardizer()
        scaler = standardizer.fit([item[1] for item in raw], split)
        normalized = standardizer.transform([item[1] for item in raw], scaler)
        preliminary = [
            DatasetSample(timestamp, symbol, features, normalized[index], label, split.name_for_index(index))
            for index, (timestamp, features, label) in enumerate(raw)
        ]
        schema_hash = self._hash({"features": scaler.feature_names, "labels": tuple(MultiHorizonLabel.__dataclass_fields__)})
        dataset_hash = self._content_hash(preliminary, schema_hash)
        end_date = timestamps[-1].astimezone(timezone.utc).strftime("%Y%m%d")
        metadata = DatasetMetadata(
            f"{symbol}_MTF_V1_{end_date}_{dataset_hash[:8]}", timestamps[-1], symbol,
            self.TIMEFRAMES, "M15", HistoricalFeatureSchema.VERSION, "phase4.labels.v1",
            timestamps[0], timestamps[-1], len(preliminary), len(scaler.feature_names),
            9, schema_hash, dataset_hash,
            split.train.start_time, split.train.end_time,
            split.validation.start_time, split.validation.end_time,
            split.test.start_time, split.test.end_time,
        )
        samples = tuple(preliminary)
        return MLDatasetArtifact(metadata, samples, scaler, split, quality_reports, self._statistics(samples))

    def _prepare(self, rows: Sequence[Any], symbol: str, timeframe: str) -> list[dict[str, Any]]:
        unique: dict[datetime, dict[str, Any]] = {}
        for row in rows:
            mapped = self._mapping(row)
            self.validator.validate_candle(mapped)
            if mapped["symbol"] != symbol or mapped["timeframe"] != timeframe:
                raise ValueError("historical candle symbol/timeframe mismatch")
            if mapped["is_closed"] is not True:
                continue
            timestamp = utc_aware(mapped["timestamp"])
            mapped["timestamp"] = timestamp
            previous = unique.get(timestamp)
            if previous and any(previous[name] != mapped[name] for name in ("open", "high", "low", "close")):
                raise ValueError("conflicting duplicate candle cannot be deduplicated safely")
            unique[timestamp] = mapped
        return [unique[key] for key in sorted(unique)]

    def _resample_missing(self, data: dict[str, list[dict[str, Any]]]) -> None:
        for source, target in (("M15", "M30"), ("M15", "H1"), ("H1", "H4"), ("H4", "D1")):
            if not data[target] and data[source]:
                data[target] = self.resampler.resample(data[source], source, target)

    @staticmethod
    def _mapping(row: Any) -> dict[str, Any]:
        get = lambda name, default=None: candle_value(row, name, default)
        source = str(get("source", get("provider", "unknown")))
        return {
            "timestamp": get("timestamp"), "symbol": str(get("symbol")).upper(),
            "timeframe": str(get("timeframe")), "open": get("open"), "high": get("high"),
            "low": get("low"), "close": get("close"), "volume": get("volume"),
            "tick_volume": get("tick_volume"), "spread": get("spread"),
            "is_closed": bool(get("is_closed", True)), "source": source,
            "provider": str(get("provider", source)),
            "provider_timestamp": get("provider_timestamp"),
            "ingested_at": get("ingested_at", get("ingestion_time")),
        }

    @classmethod
    def _content_hash(cls, samples: Sequence[DatasetSample], schema_hash: str) -> str:
        content = {
            "schema_hash": schema_hash,
            "rows": [{
                "timestamp": sample.timestamp.isoformat(), "symbol": sample.symbol,
                "features": sample.features, "normalized": sample.normalized_features,
                "label": asdict(sample.label), "split": sample.split,
            } for sample in samples],
        }
        return cls._hash(content)

    @staticmethod
    def _hash(value: Any) -> str:
        def default(item: Any) -> str:
            return item.isoformat() if isinstance(item, datetime) else str(item)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _statistics(samples: Sequence[DatasetSample]) -> dict[str, Any]:
        classes = {name: sum(sample.label.classification == name for sample in samples) for name in ("UP", "DOWN", "NEUTRAL")}
        returns = [sample.label.future_return_5 for sample in samples]
        volatility = [sample.features["atr_percent"] for sample in samples]
        return {
            "total_samples": len(samples), **{f"{name.lower()}_samples": count for name, count in classes.items()},
            "class_distribution": {name: count / len(samples) for name, count in classes.items()},
            "mean_return": mean(returns), "median_return": median(returns),
            "std_return": pstdev(returns) if len(returns) > 1 else 0.0,
            "mean_mfe": mean(sample.label.maximum_favorable_excursion for sample in samples),
            "mean_mae": mean(sample.label.maximum_adverse_excursion for sample in samples),
            "volatility": {"minimum": min(volatility), "maximum": max(volatility), "mean": mean(volatility)},
        }


class DatasetExporter:
    def export(self, artifact: MLDatasetArtifact, output_directory: str | Path) -> dict[str, Path]:
        import pandas as pd

        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = artifact.metadata.dataset_id
        paths = {
            "features": directory / f"{stem}_features.parquet",
            "labels": directory / f"{stem}_labels.parquet",
            "metadata": directory / f"{stem}_dataset_metadata.json",
        }
        if any(path.exists() for path in paths.values()):
            if paths["metadata"].exists():
                existing = json.loads(paths["metadata"].read_text(encoding="utf-8"))
                if existing.get("dataset_hash") == artifact.metadata.dataset_hash and all(path.exists() for path in paths.values()):
                    return paths
            raise FileExistsError("immutable dataset artifact already exists; choose a new version or input")
        feature_rows = [{
            "timestamp": sample.timestamp, "symbol": sample.symbol, "split": sample.split,
            **sample.normalized_features,
        } for sample in artifact.samples]
        label_rows = [asdict(sample.label) for sample in artifact.samples]
        pd.DataFrame(feature_rows).to_parquet(paths["features"], index=False)
        pd.DataFrame(label_rows).to_parquet(paths["labels"], index=False)
        payload = {
            **self._jsonable(asdict(artifact.metadata)),
            "scaler": self._jsonable(asdict(artifact.scaler)),
            "quality_reports": self._jsonable({key: asdict(value) for key, value in artifact.quality_reports.items()}),
            "statistics": self._jsonable(artifact.statistics),
        }
        paths["metadata"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return paths

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        return value
