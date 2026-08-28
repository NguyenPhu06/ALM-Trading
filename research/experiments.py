"""Experiment configuration and versioning (sections 2 and 5).

Strategies are *configured*, not hardcoded. `CATALOGUE` holds the eight
experiments section 2 names; each is a declaration of which feature families the
arm is allowed to read, so an ablation is a config change rather than a new
branch of code.

Every result records the ten fields section 5 requires, and `ExperimentSpec`
hashes them into an `experiment_id`. Re-running the same configuration over the
same dataset reproduces the same id; changing any input changes it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ai.dataset.versioning import FEATURE_VERSION, LABEL_VERSION
from ai.edge.evidence import EvidenceSource
from research.metrics import PerformanceMetrics, evaluate
from research.models import ResearchObservation, require_forward_only

# The feature families an arm may switch on. These are the names the ablation and
# indicator-value studies use, and they map onto ai.dataset.features FEATURE_GROUPS.
FEATURE_FAMILIES = ("market_structure", "liquidity", "ichimoku", "rsi", "adx", "atr",
                    "session", "mtf", "spread_volatility", "nn")

# Section 2's list, as configuration.
CATALOGUE: dict[str, tuple[str, ...]] = {
    "smc": ("liquidity", "market_structure"),
    "ichimoku": ("ichimoku",),
    "rsi": ("rsi",),
    "adx": ("adx",),
    "indicators": ("ichimoku", "rsi", "adx"),
    "smc_indicators": ("liquidity", "market_structure", "ichimoku", "rsi", "adx"),
    "smc_nn": ("liquidity", "market_structure", "nn"),
    "smc_nn_indicators": ("liquidity", "market_structure", "nn", "ichimoku", "rsi", "adx"),
}


class UnknownFeatureFamily(ValueError):
    """Raised when a configuration names a feature family that does not exist."""


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    name: str
    features: tuple[str, ...]
    description: str = ""
    timeframes: tuple[str, ...] = ()
    uses_nn: bool = False
    dca_levels: int = 0
    exit_kind: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = [name for name in self.features if name not in FEATURE_FAMILIES]
        if unknown:
            raise UnknownFeatureFamily(f"unknown feature families: {unknown}")

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "features": list(self.features),
                "description": self.description, "timeframes": list(self.timeframes),
                "uses_nn": self.uses_nn or "nn" in self.features,
                "dca_levels": self.dca_levels, "exit_kind": self.exit_kind,
                **self.context}


def configured(name: str, **overrides: Any) -> ExperimentConfig:
    """Build one of the catalogue experiments, optionally adjusted."""
    if name not in CATALOGUE:
        raise KeyError(f"unknown experiment: {name}")
    features = tuple(overrides.pop("features", CATALOGUE[name]))
    return ExperimentConfig(name=name, features=features,
                            description=overrides.pop("description", name),
                            uses_nn="nn" in features, **overrides)


def catalogue() -> list[ExperimentConfig]:
    return [configured(name) for name in CATALOGUE]


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """Section 5. The ten fields that make a result reproducible."""

    strategy_version: str
    feature_version: str = FEATURE_VERSION
    model_version: str | None = None
    dataset_version: str | None = None
    label_version: str = LABEL_VERSION
    training_range: tuple[datetime | None, datetime | None] = (None, None)
    validation_range: tuple[datetime | None, datetime | None] = (None, None)
    test_range: tuple[datetime | None, datetime | None] = (None, None)
    config: ExperimentConfig | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def experiment_id(self) -> str:
        """Content hash of everything that could change the result.

        `timestamp` is deliberately excluded: re-running the same configuration
        over the same data must reproduce the same id, otherwise the multiple
        testing ledger would count one hypothesis twice.
        """
        payload = json.dumps({
            "strategy_version": self.strategy_version,
            "feature_version": self.feature_version,
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "label_version": self.label_version,
            "training_range": _range(self.training_range),
            "validation_range": _range(self.validation_range),
            "test_range": _range(self.test_range),
            "config": self.config.as_dict() if self.config else None,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "strategy_version": self.strategy_version,
            "feature_version": self.feature_version,
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "label_version": self.label_version,
            "training_range": _range(self.training_range),
            "validation_range": _range(self.validation_range),
            "test_range": _range(self.test_range),
            "config": self.config.as_dict() if self.config else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    spec: ExperimentSpec
    metrics: PerformanceMetrics
    observations: int
    evidence: EvidenceSource = EvidenceSource.FORWARD_OBSERVATION
    notes: tuple[str, ...] = ()

    @property
    def experiment_id(self) -> str:
        return self.spec.experiment_id

    @property
    def name(self) -> str:
        return self.spec.config.name if self.spec.config else self.spec.strategy_version

    def as_dict(self) -> dict[str, Any]:
        return {"experiment_id": self.experiment_id, "name": self.name,
                "spec": self.spec.as_dict(), "metrics": self.metrics.as_dict(),
                "observations": self.observations, "evidence": str(self.evidence),
                "notes": list(self.notes),
                # Research measures; it never places anything.
                "orders_sent": 0}


class ExperimentRunner:
    """Evaluates a configuration over forward observations. Runs no strategy code."""

    def __init__(self, *, minimum_samples: int = 30, ledger: Any = None):
        self.minimum_samples = int(minimum_samples)
        self.ledger = ledger

    def run(self, config: ExperimentConfig,
            observations: Sequence[ResearchObservation], *,
            spec: ExperimentSpec | None = None,
            strategy_version: str = "v1", **spec_fields: Any) -> ExperimentResult:
        rows = require_forward_only(observations)
        spec = spec or ExperimentSpec(strategy_version=strategy_version, config=config,
                                      **spec_fields)
        metrics = evaluate(rows, minimum_samples=self.minimum_samples)
        notes: list[str] = []
        if not metrics.reliable:
            notes.append(f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}")
        result = ExperimentResult(spec, metrics, len(rows), notes=tuple(notes))
        if self.ledger is not None:
            self.ledger.record(result)
        return result

    def run_many(self, configs: Sequence[ExperimentConfig],
                 by_config: Mapping[str, Sequence[ResearchObservation]],
                 **spec_fields: Any) -> list[ExperimentResult]:
        return [self.run(config, by_config.get(config.name, ()), **spec_fields)
                for config in configs]


def compare(results: Sequence[ExperimentResult], *,
            metric: str = "expectancy") -> dict[str, Any]:
    """Rank experiments. Unreliable arms are ranked but flagged, never hidden."""
    scored = [(result, getattr(result.metrics, metric, None)) for result in results]
    ranked = sorted((item for item in scored if item[1] is not None),
                    key=lambda item: item[1], reverse=True)
    return {
        "metric": metric,
        "ranking": [{"name": result.name, "experiment_id": result.experiment_id,
                     metric: value, "sample_size": result.metrics.sample_size,
                     "reliable": result.metrics.reliable}
                    for result, value in ranked],
        "best": ranked[0][0].name if ranked else None,
        "best_reliable": next((result.name for result, _ in ranked
                               if result.metrics.reliable), None),
        "unscored": [result.name for result, value in scored if value is None],
    }


def _range(value: tuple[datetime | None, datetime | None]) -> list[str | None]:
    return [item.isoformat() if isinstance(item, datetime) else None for item in value]
