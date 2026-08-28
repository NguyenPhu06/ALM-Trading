"""Dataset quality and explicit leakage protection.

Six leakage classes are checked (section 8). Each has its own code so a failure
names the specific mistake rather than reporting a generic "invalid dataset".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Sequence


class LeakageCode(StrEnum):
    FUTURE_CANDLE_LEAKAGE = "FUTURE_CANDLE_LEAKAGE"
    FUTURE_INDICATOR_LEAKAGE = "FUTURE_INDICATOR_LEAKAGE"
    FUTURE_NORMALIZATION_LEAKAGE = "FUTURE_NORMALIZATION_LEAKAGE"
    FUTURE_SCALING_LEAKAGE = "FUTURE_SCALING_LEAKAGE"
    FUTURE_TARGET_LEAKAGE = "FUTURE_TARGET_LEAKAGE"
    RANDOM_SPLIT_LEAKAGE = "RANDOM_SPLIT_LEAKAGE"
    NON_CHRONOLOGICAL = "NON_CHRONOLOGICAL"
    DUPLICATE_ROW = "DUPLICATE_ROW"
    MISSING_VALUES = "MISSING_VALUES"
    FEATURE_VERSION_MIXED = "FEATURE_VERSION_MIXED"
    LABEL_VERSION_MIXED = "LABEL_VERSION_MIXED"
    INSUFFICIENT_ROWS = "INSUFFICIENT_ROWS"


@dataclass(frozen=True, slots=True)
class QualityReport:
    ok: bool
    codes: tuple[str, ...] = ()
    row_count: int = 0
    duplicate_count: int = 0
    missing_values: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "codes": list(self.codes), "row_count": self.row_count,
                "duplicate_count": self.duplicate_count,
                "missing_values": self.missing_values, **self.details}


class DatasetQualityChecker:
    def __init__(self, *, minimum_rows: int = 1):
        self.minimum_rows = int(minimum_rows)

    def check(self, rows: Sequence[Any], *, feature_version: str | None = None,
              label_version: str | None = None) -> QualityReport:
        codes: list[str] = []
        details: dict[str, Any] = {}
        if len(rows) < self.minimum_rows:
            codes.append(LeakageCode.INSUFFICIENT_ROWS)

        timestamps = [row.timestamp for row in rows]
        if timestamps != sorted(timestamps):
            codes.append(LeakageCode.NON_CHRONOLOGICAL)

        seen: set[tuple[Any, Any]] = set()
        duplicates = 0
        for row in rows:
            key = (row.timestamp, row.symbol)
            if key in seen:
                duplicates += 1
            seen.add(key)
        if duplicates:
            codes.append(LeakageCode.DUPLICATE_ROW)

        missing = 0
        for row in rows:
            for value in row.values:
                if value is None or value != value:
                    missing += 1
        if missing:
            codes.append(LeakageCode.MISSING_VALUES)

        if feature_version is not None:
            versions = {row.feature_version for row in rows}
            details["feature_versions"] = sorted(versions)
            if versions - {feature_version}:
                codes.append(LeakageCode.FEATURE_VERSION_MIXED)
        if label_version is not None:
            versions = {getattr(row, "label_version", label_version) for row in rows}
            details["label_versions"] = sorted(versions)
            if versions - {label_version}:
                codes.append(LeakageCode.LABEL_VERSION_MIXED)

        return QualityReport(not codes, tuple(dict.fromkeys(codes)), len(rows),
                             duplicates, missing, details)

    # ---------------------------------------------------------------- leakage
    @staticmethod
    def check_target_leakage(rows: Sequence[Any]) -> QualityReport:
        """A label must resolve strictly after the observation it belongs to."""
        codes: list[str] = []
        offenders: list[str] = []
        for row in rows:
            resolved = getattr(row, "label_resolved_at", None)
            if resolved is not None and resolved <= row.timestamp:
                offenders.append(str(row.timestamp))
        if offenders:
            codes.append(LeakageCode.FUTURE_TARGET_LEAKAGE)
        return QualityReport(not codes, tuple(codes), len(rows),
                             details={"offenders": offenders[:10]})

    @staticmethod
    def check_split_leakage(split_bounds: dict[str, tuple[datetime, datetime]]) -> QualityReport:
        """Splits must be chronological and non-overlapping."""
        codes: list[str] = []
        order = ["train", "validation", "test"]
        present = [name for name in order if name in split_bounds]
        for earlier, later in zip(present, present[1:]):
            if split_bounds[earlier][1] > split_bounds[later][0]:
                codes.append(LeakageCode.RANDOM_SPLIT_LEAKAGE)
        return QualityReport(not codes, tuple(dict.fromkeys(codes)),
                             details={"bounds": {k: [v[0], v[1]] for k, v in split_bounds.items()}})

    @staticmethod
    def check_scaler_leakage(scaler_rows: int, train_rows: int) -> QualityReport:
        """The scaler must have been fitted on the training rows and no more."""
        codes: list[str] = []
        if scaler_rows > train_rows:
            codes.append(LeakageCode.FUTURE_SCALING_LEAKAGE)
            codes.append(LeakageCode.FUTURE_NORMALIZATION_LEAKAGE)
        return QualityReport(not codes, tuple(codes),
                             details={"scaler_rows": scaler_rows, "train_rows": train_rows})

    @staticmethod
    def check_feature_causality(rows: Sequence[Any]) -> QualityReport:
        """No feature row may carry a source timestamp ahead of its own timestamp."""
        codes: list[str] = []
        offenders = []
        for row in rows:
            source = (row.context or {}).get("source_timestamp")
            if isinstance(source, datetime) and source > row.timestamp:
                offenders.append(str(row.timestamp))
        if offenders:
            codes.append(LeakageCode.FUTURE_CANDLE_LEAKAGE)
            codes.append(LeakageCode.FUTURE_INDICATOR_LEAKAGE)
        return QualityReport(not codes, tuple(codes), len(rows),
                             details={"offenders": offenders[:10]})
