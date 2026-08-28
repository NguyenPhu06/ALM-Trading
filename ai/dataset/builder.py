"""Build a training dataset from real forward observation data.

    observations -> features -> (wait for horizon) -> labels -> chronological
    split -> train-only scaler -> audit

The builder never labels an observation whose horizon has not elapsed, never
shuffles, and never lets the scaler see anything outside TRAIN. Each of those is
verified by the quality checker before the dataset is returned.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from ai.dataset.features import FeatureExtractor, FeatureRow
from ai.dataset.labels import Direction, ForwardLabel, LabelingEngine, LabelRefusal
from ai.dataset.quality import DatasetQualityChecker, LeakageCode, QualityReport
from ai.dataset.split import ChronologicalSplit, build_splitter, split_bounds
from ai.dataset.versioning import (
    FEATURE_VERSION,
    LABEL_VERSION,
    PREPROCESSING_VERSION,
    DatasetAudit,
    dataset_id,
)
from ai.datasets.split import ScalerState, TrainOnlyStandardizer
from config.settings import load_yaml

logger = logging.getLogger(__name__)

# A constant feature can carry a std of ~1e-18 rather than exactly 0, and `or 1.0`
# does not catch that. Dividing float noise by 1e-18 explodes, so guard on epsilon.
MINIMUM_DEVIATION = 1e-12

DIRECTION_INDEX = {Direction.UP: 0, Direction.DOWN: 1, Direction.NEUTRAL: 2}
DIRECTION_NAMES = ("UP", "DOWN", "NEUTRAL")


@dataclass(frozen=True, slots=True)
class DatasetRow:
    timestamp: datetime
    symbol: str
    names: tuple[str, ...]
    values: tuple[float, ...]
    label: ForwardLabel
    feature_version: str
    label_version: str
    regime: str
    session: str
    timeframe: str
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def label_resolved_at(self) -> datetime | None:
        return self.label.resolved_at

    @property
    def direction_index(self) -> int:
        return DIRECTION_INDEX[self.label.direction]


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    rows: tuple[DatasetRow, ...]

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def matrix(self) -> np.ndarray:
        if not self.rows:
            return np.empty((0, 0), dtype=float)
        return np.asarray([row.values for row in self.rows], dtype=float)

    @property
    def direction_labels(self) -> np.ndarray:
        return np.asarray([row.direction_index for row in self.rows], dtype=int)

    def targets(self, name: str) -> np.ndarray:
        return np.asarray([getattr(row.label, name) for row in self.rows], dtype=float)


@dataclass(frozen=True, slots=True)
class BuiltDataset:
    dataset_id: str
    feature_names: tuple[str, ...]
    train: Partition
    validation: Partition
    test: Partition
    scaler: ScalerState
    audit: DatasetAudit
    quality: QualityReport
    horizon: str
    split: ChronologicalSplit | None = None
    refusals: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.quality.ok and len(self.train) > 0

    def scaled(self, partition: Partition) -> np.ndarray:
        """Apply the TRAIN-fitted scaler. Validation and test never refit."""
        if not partition.rows:
            return np.empty((0, len(self.feature_names)), dtype=float)
        means = np.asarray([self.scaler.means[name] for name in self.feature_names], dtype=float)
        deviations = np.asarray(
            [self.scaler.standard_deviations.get(name, 1.0) for name in self.feature_names],
            dtype=float)
        deviations[np.abs(deviations) < MINIMUM_DEVIATION] = 1.0
        return (partition.matrix - means) / deviations

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id, "horizon": self.horizon,
            "feature_count": len(self.feature_names),
            "train_rows": len(self.train), "validation_rows": len(self.validation),
            "test_rows": len(self.test), "audit": self.audit.as_dict(),
            "quality": self.quality.as_dict(), "refusals": dict(self.refusals),
            "preprocessing_version": self.scaler.fitted_split and PREPROCESSING_VERSION,
        }


class DatasetBuilder:
    """Turns observation records plus future candles into a leak-free dataset."""

    def __init__(self, *, extractor: FeatureExtractor | None = None,
                 labeler: LabelingEngine | None = None,
                 minimum_rows: int | None = None):
        config = load_yaml().get("phase_13", {})
        self.extractor = extractor or FeatureExtractor()
        self.labeler = labeler or LabelingEngine()
        self.default_horizon = str(config.get("default_horizon", "1h"))
        self.minimum_rows = int(minimum_rows if minimum_rows is not None
                                else config.get("minimum_observations", 200))
        self.checker = DatasetQualityChecker(minimum_rows=1)

    # ------------------------------------------------------------------ build
    def build(self, observations: Sequence[Mapping[str, Any]],
              future_candles: Sequence[Mapping[str, Any]], *, horizon: str | None = None,
              now: datetime | None = None, symbol: str | None = None,
              timeframe: str = "M5", source: str = "forward_observation") -> BuiltDataset:
        """`now` is the moment the dataset is built; horizons past it are refused."""
        horizon = horizon or self.default_horizon
        moment = now or datetime.now(timezone.utc)
        candles = sorted(
            (row for row in future_candles if row.get("timestamp") is not None),
            key=lambda row: row["timestamp"])

        rows: list[DatasetRow] = []
        refusals: dict[str, int] = {}
        for observation in sorted(observations, key=lambda item: item.get("timestamp")):
            feature_row = self.extractor.extract(observation)
            if feature_row.timestamp is None:
                refusals["NO_TIMESTAMP"] = refusals.get("NO_TIMESTAMP", 0) + 1
                continue
            entry = float(feature_row.context.get("price") or 0.0)
            window = [row for row in candles if row["timestamp"] > feature_row.timestamp]
            result = self.labeler.label(
                entry_price=entry, entry_time=feature_row.timestamp, future=window,
                horizon=horizon, spread=float(feature_row.context.get("spread") or 0.0),
                now=moment)
            if not result.ok:
                code = str(result.refusal or LabelRefusal.NO_FUTURE_DATA)
                refusals[code] = refusals.get(code, 0) + 1
                continue
            rows.append(DatasetRow(
                timestamp=feature_row.timestamp, symbol=feature_row.symbol or (symbol or ""),
                names=feature_row.names, values=feature_row.values, label=result.label,
                feature_version=feature_row.feature_version, label_version=LABEL_VERSION,
                regime=feature_row.regime, session=feature_row.session, timeframe=timeframe,
                context=dict(feature_row.context)))

        return self._assemble(rows, horizon=horizon, symbol=symbol, timeframe=timeframe,
                              source=source, refusals=refusals)

    # --------------------------------------------------------------- assembly
    def _assemble(self, rows: list[DatasetRow], *, horizon: str, symbol: str | None,
                  timeframe: str, source: str, refusals: dict[str, int]) -> BuiltDataset:
        feature_names = rows[0].names if rows else ()
        quality_codes: list[str] = []

        report = self.checker.check(rows, feature_version=FEATURE_VERSION,
                                    label_version=LABEL_VERSION)
        quality_codes.extend(report.codes)
        quality_codes.extend(self.checker.check_target_leakage(rows).codes)
        quality_codes.extend(self.checker.check_feature_causality(rows).codes)

        split: ChronologicalSplit | None = None
        train_rows: list[DatasetRow] = []
        validation_rows: list[DatasetRow] = []
        test_rows: list[DatasetRow] = []

        if len(rows) >= 3 and not report.codes:
            timestamps = [row.timestamp for row in rows]
            split = build_splitter().split(timestamps)
            train_rows = rows[split.train.start_index:split.train.end_index + 1]
            validation_rows = rows[split.validation.start_index:split.validation.end_index + 1]
            test_rows = rows[split.test.start_index:split.test.end_index + 1]
            quality_codes.extend(
                DatasetQualityChecker.check_split_leakage(split_bounds(split)).codes)
        elif rows:
            train_rows = rows

        scaler = self._fit_scaler(train_rows, feature_names)
        quality_codes.extend(
            DatasetQualityChecker.check_scaler_leakage(len(train_rows), len(train_rows)).codes)

        distribution: dict[str, int] = {name: 0 for name in DIRECTION_NAMES}
        for row in rows:
            distribution[str(row.label.direction)] += 1

        audit = DatasetAudit(
            dataset_id=dataset_id(
                feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
                symbols=[symbol or (rows[0].symbol if rows else "")],
                timeframes=[timeframe], horizon=horizon, rows=len(rows),
                start=rows[0].timestamp if rows else None,
                end=rows[-1].timestamp if rows else None),
            feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
            preprocessing_version=PREPROCESSING_VERSION,
            start=rows[0].timestamp if rows else None,
            end=rows[-1].timestamp if rows else None,
            symbols=tuple({row.symbol for row in rows}) or ((symbol,) if symbol else ()),
            timeframes=(timeframe,), row_count=len(rows),
            class_distribution=distribution, missing_values=report.missing_values,
            duplicate_count=report.duplicate_count, source=source, horizon=horizon,
            notes=tuple(f"{code}={count}" for code, count in sorted(refusals.items())))

        if len(rows) < self.minimum_rows:
            quality_codes.append(LeakageCode.INSUFFICIENT_ROWS)

        codes = tuple(dict.fromkeys(quality_codes))
        quality = QualityReport(not codes, codes, len(rows), report.duplicate_count,
                                report.missing_values, report.details)

        return BuiltDataset(
            dataset_id=audit.dataset_id, feature_names=feature_names,
            train=Partition("TRAIN", tuple(train_rows)),
            validation=Partition("VALIDATION", tuple(validation_rows)),
            test=Partition("TEST", tuple(test_rows)),
            scaler=scaler, audit=audit, quality=quality, horizon=horizon,
            split=split, refusals=refusals)

    @staticmethod
    def _fit_scaler(train_rows: Sequence[DatasetRow],
                    feature_names: Sequence[str]) -> ScalerState:
        """Fitted on TRAIN rows only. Validation and test reuse this state."""
        if not train_rows or not feature_names:
            return ScalerState(tuple(feature_names), {}, {}, "TRAIN")
        matrix = np.asarray([row.values for row in train_rows], dtype=float)
        means = matrix.mean(axis=0)
        deviations = matrix.std(axis=0, ddof=0)
        # A constant column gets a deviation of 1.0 so it scales to exactly zero.
        deviations[np.abs(deviations) < MINIMUM_DEVIATION] = 1.0
        return ScalerState(
            tuple(feature_names),
            {name: float(means[index]) for index, name in enumerate(feature_names)},
            {name: float(deviations[index]) for index, name in enumerate(feature_names)},
            "TRAIN")
