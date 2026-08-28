"""The explicit training job for forward-observation data.

This is the ONLY place a model is fitted. It is never called from the observation
loop, never from inference, and it never promotes anything: it produces a
registered EXPERIMENTAL/VALIDATED record and a comparison, and stops there.

    dataset -> train -> validate -> test -> walk-forward -> baselines
        -> calibration -> segments -> explainability -> edge verdict -> register
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

import numpy as np

from ai.dataset.builder import BuiltDataset, Partition
from ai.datasets.walk_forward import ExpandingWalkForward
from ai.evaluation.calibration import calibration_report
from ai.evaluation.explainability import PermutationImportance
from ai.evaluation.metrics import classification_metrics
from ai.evaluation.segmented import SegmentedEvaluator, trading_metrics
from ai.evaluation.significance import EdgeVerdict, SignificanceEvaluator
from ai.model_registry.records import ModelRecord, ModelState, ModelTask
from ai.models.multitask import MultiTaskConfig, MultiTaskMLP
from ai.models.rule_baselines import all_baselines
from config.settings import Settings, get_settings, load_yaml

logger = logging.getLogger(__name__)


def probabilistic_scores(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    """Multi-class Brier score and log loss.

    Neither is produced by the Phase 4/5 evaluators, and the champion/challenger
    comparison keys off both, so they are computed here rather than inferred.
    """
    if not len(labels):
        return {"brier_score": None, "log_loss": None}
    one_hot = np.zeros_like(probabilities, dtype=float)
    one_hot[np.arange(len(labels)), labels] = 1.0
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    picked = np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0)
    return {"brier_score": brier, "log_loss": float(-np.mean(np.log(picked)))}


class TrainingDisabled(RuntimeError):
    """Raised when a training job runs with AI_TRAINING_ENABLED false."""


@dataclass(frozen=True, slots=True)
class TrainingReport:
    model_id: str
    record: ModelRecord
    history: dict[str, Any]
    baselines: dict[str, float]
    beats_all_baselines: bool
    edge: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)

    @property
    def edge_detected(self) -> bool:
        return self.record.edge_verdict == str(EdgeVerdict.EDGE_DETECTED)

    def as_dict(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "record": self.record.as_dict(),
                "history": dict(self.history), "baselines": dict(self.baselines),
                "beats_all_baselines": self.beats_all_baselines, "edge": dict(self.edge)}


class ForwardTrainer:
    """Trains on a BuiltDataset. Explicit job only."""

    def __init__(self, settings: Settings | None = None, *,
                 config: MultiTaskConfig | None = None,
                 significance: SignificanceEvaluator | None = None,
                 segmented: SegmentedEvaluator | None = None):
        self.settings = settings or get_settings()
        phase = load_yaml().get("phase_13", {})
        self.config = config or MultiTaskConfig()
        self.significance = significance or SignificanceEvaluator()
        self.segmented = segmented or SegmentedEvaluator()
        self.walk_forward_config = phase.get("walk_forward", {})

    def train(self, dataset: BuiltDataset, *, task: ModelTask | None = None,
              model_version: str | None = None) -> TrainingReport:
        if not self.settings.ai_training_enabled:
            raise TrainingDisabled("AI_TRAINING_ENABLED is false")
        if not dataset.train.rows:
            raise ValueError("cannot train on an empty training partition")

        task = task or ModelTask(symbol=dataset.audit.symbols[0] if dataset.audit.symbols
                                 else "EURUSD",
                                 timeframe=dataset.audit.timeframes[0]
                                 if dataset.audit.timeframes else "M5")

        train_matrix = dataset.scaled(dataset.train)
        validation_matrix = dataset.scaled(dataset.validation)
        test_matrix = dataset.scaled(dataset.test)

        model = MultiTaskMLP(train_matrix.shape[1], self.config)
        history = model.fit(self._bundle(dataset.train, train_matrix),
                            self._bundle(dataset.validation, validation_matrix)
                            if dataset.validation.rows else None)

        validation_metrics = self._metrics(model, dataset.validation, validation_matrix)
        test_metrics = self._metrics(model, dataset.test, test_matrix)

        baselines = self._baselines(dataset, train_matrix, test_matrix)
        model_accuracy = float(test_metrics.get("accuracy") or 0.0)
        beats_all = bool(baselines) and all(model_accuracy > score for score in baselines.values())

        calibration = self._calibration(model, dataset.test, test_matrix)
        walk_forward = self._walk_forward(dataset)
        regime_metrics, session_metrics = self._segments(model, dataset.test, test_matrix)
        explain = self._explain(model, dataset, test_matrix)
        edge = self._edge(dataset.test, beats_all)

        model_id = uuid4().hex[:12]
        record = ModelRecord(
            model_id=model_id,
            model_version=model_version or MultiTaskMLP.ARCHITECTURE_VERSION,
            task=task, feature_version=dataset.audit.feature_version,
            label_version=dataset.audit.label_version,
            training_dataset_version=dataset.dataset_id,
            preprocessing_version=dataset.audit.preprocessing_version,
            state=ModelState.EXPERIMENTAL,
            training_timestamp=datetime.now(timezone.utc),
            validation_metrics=validation_metrics, test_metrics=test_metrics,
            walk_forward_metrics=walk_forward, regime_metrics=regime_metrics,
            session_metrics=session_metrics,
            baseline_comparison={"scores": baselines, "model_accuracy": model_accuracy,
                                 "beats_all_baselines": beats_all},
            calibration=calibration, explainability=explain,
            edge_verdict=edge["verdict"],
            notes=tuple(history.warnings),
        )
        logger.info("trained model %s edge=%s beats_baselines=%s",
                    model_id, edge["verdict"], beats_all)
        return TrainingReport(model_id, record, history.as_dict(), baselines, beats_all,
                              edge, model.parameters())

    # ------------------------------------------------------------------ pieces
    @staticmethod
    def _bundle(partition: Partition, matrix: np.ndarray) -> dict[str, np.ndarray]:
        return {
            "features": matrix,
            "direction": partition.direction_labels,
            "regression": np.column_stack([
                partition.targets("future_return"), partition.targets("future_mfe"),
                partition.targets("future_mae")]),
            "volatility": (partition.targets("future_volatility")
                           > np.median(partition.targets("future_volatility"))
                           if len(partition) else np.zeros(0)).astype(float),
        }

    def _metrics(self, model: MultiTaskMLP, partition: Partition,
                 matrix: np.ndarray) -> dict[str, Any]:
        if not partition.rows:
            return {}
        probabilities = model.predict_proba(matrix)
        labels = partition.direction_labels
        payload: dict[str, Any] = {"samples": len(partition)}
        try:
            payload.update(classification_metrics(labels, probabilities).as_dict())
        except Exception:
            payload["accuracy"] = float((probabilities.argmax(axis=1) == labels).mean())
        payload.setdefault("accuracy", float((probabilities.argmax(axis=1) == labels).mean()))
        payload.update(probabilistic_scores(labels, probabilities))

        outputs = model.predict(matrix)
        actual_return = partition.targets("future_return")
        predicted_return = np.asarray([item.expected_return for item in outputs])
        payload["regression_mae"] = float(np.mean(np.abs(predicted_return - actual_return)))
        payload["regression_rmse"] = float(np.sqrt(np.mean((predicted_return - actual_return) ** 2)))
        payload["directional_accuracy"] = float(
            np.mean(np.sign(predicted_return) == np.sign(actual_return)))

        # Trading-oriented metrics use the NET (cost-aware) return.
        net = partition.targets("net_return")
        payload.update(trading_metrics(net.tolist()))
        payload["net_expectancy"] = payload.get("expectancy")
        payload["mfe"] = float(np.mean(partition.targets("future_mfe")))
        payload["mae"] = float(np.mean(partition.targets("future_mae")))
        return payload

    def _baselines(self, dataset: BuiltDataset, train_matrix: np.ndarray,
                   test_matrix: np.ndarray) -> dict[str, float]:
        if not dataset.test.rows:
            return {}
        scores: dict[str, float] = {}
        labels = dataset.test.direction_labels
        for name, baseline in all_baselines(dataset.feature_names).items():
            try:
                baseline.fit(train_matrix, dataset.train.direction_labels)
                predicted = baseline.predict_proba(test_matrix)
                scores[name] = float((predicted.argmax(axis=1) == labels).mean())
            except Exception:
                logger.exception("baseline %s failed", name)
        return scores

    def _calibration(self, model: MultiTaskMLP, partition: Partition,
                     matrix: np.ndarray) -> dict[str, Any]:
        if not partition.rows:
            return {}
        labels = partition.direction_labels
        probabilities = model.predict_proba(matrix)
        scores = probabilistic_scores(labels, probabilities)
        try:
            report = calibration_report(labels, probabilities, bins=10)
        except Exception:
            logger.exception("calibration failed")
            return scores
        errors = dict(report.expected_calibration_error)
        return {
            **scores,
            "expected_calibration_error": errors,
            "mean_calibration_error": (float(np.mean(list(errors.values())))
                                       if errors else None),
            "bins_per_class": {name: len(bins) for name, bins in report.bins_by_class.items()},
            "warning": report.warning,
        }

    def _walk_forward(self, dataset: BuiltDataset) -> dict[str, Any]:
        rows = (*dataset.train.rows, *dataset.validation.rows, *dataset.test.rows)
        timestamps = [row.timestamp for row in rows]
        config = self.walk_forward_config
        try:
            windows = list(ExpandingWalkForward(
                initial_train_size=int(config.get("initial_train_size", 200)),
                validation_size=int(config.get("validation_size", 50)),
                test_size=int(config.get("test_size", 50)),
                step_size=int(config.get("step_size", 50))).windows(timestamps))
        except Exception:
            return {"windows": 0, "mean_accuracy": None, "stability": None,
                    "reason": "INSUFFICIENT_DATA"}
        if not windows:
            return {"windows": 0, "mean_accuracy": None, "stability": None,
                    "reason": "INSUFFICIENT_DATA"}

        scores: list[float] = []
        for window in windows:
            # WalkForwardWindow carries timestamps, so select by time rather than
            # by index; slicing on the datetimes would silently produce nonsense.
            train_rows = [row for row in rows
                          if window.train_start <= row.timestamp <= window.train_end]
            test_rows = [row for row in rows
                         if window.test_start <= row.timestamp <= window.test_end]
            if len(train_rows) < 10 or not test_rows:
                continue
            matrix = np.asarray([row.values for row in train_rows], dtype=float)
            mean, deviation = matrix.mean(axis=0), matrix.std(axis=0)
            deviation[deviation == 0] = 1.0
            model = MultiTaskMLP(matrix.shape[1], self.config)
            model.fit({"features": (matrix - mean) / deviation,
                       "direction": np.asarray([row.direction_index for row in train_rows]),
                       "regression": np.zeros((len(train_rows), 3)),
                       "volatility": np.zeros(len(train_rows))})
            test = (np.asarray([row.values for row in test_rows], dtype=float) - mean) / deviation
            labels = np.asarray([row.direction_index for row in test_rows])
            scores.append(float((model.predict_proba(test).argmax(axis=1) == labels).mean()))

        if not scores:
            return {"windows": len(windows), "mean_accuracy": None, "stability": None,
                    "reason": "NO_USABLE_WINDOW"}
        mean_accuracy = float(np.mean(scores))
        spread = float(np.std(scores))
        return {"windows": len(scores), "scores": scores, "mean_accuracy": mean_accuracy,
                "std": spread, "min": min(scores), "max": max(scores),
                "stability": float(max(0.0, 1.0 - spread / mean_accuracy)) if mean_accuracy else 0.0}

    def _segments(self, model: MultiTaskMLP, partition: Partition,
                  matrix: np.ndarray) -> tuple[dict[str, Any], dict[str, Any]]:
        if not partition.rows:
            return {}, {}
        probabilities = model.predict_proba(matrix)
        labels = partition.direction_labels
        returns = partition.targets("net_return")

        regime = self.segmented.by_regime(
            labels=labels, probabilities=probabilities, returns=returns,
            segments=[row.regime for row in partition.rows])
        session = self.segmented.by_session(
            labels=labels, probabilities=probabilities, returns=returns,
            segments=[row.session for row in partition.rows])

        def summarise(report) -> dict[str, Any]:
            payload = report.as_dict()
            weakest = report.weakest
            payload["worst_expectancy"] = weakest.expectancy if weakest else None
            payload["worst_segment"] = weakest.segment if weakest else None
            return payload

        return summarise(regime), summarise(session)

    def _explain(self, model: MultiTaskMLP, dataset: BuiltDataset,
                 matrix: np.ndarray) -> dict[str, Any]:
        if not dataset.test.rows:
            return {}
        try:
            report = PermutationImportance(repeats=3).explain(
                model.predict_proba, matrix, dataset.test.direction_labels,
                dataset.feature_names)
            return report.as_dict()
        except Exception:
            logger.exception("explainability failed")
            return {}

    def _edge(self, partition: Partition, beats_all: bool) -> dict[str, Any]:
        if not partition.rows:
            return {"verdict": str(EdgeVerdict.INSUFFICIENT_DATA), "reasons": ["NO_TEST_DATA"]}
        report = self.significance.evaluate(partition.targets("net_return").tolist())
        payload = report.as_dict()
        if not beats_all:
            # Statistical significance is never enough on its own, and the audit
            # should show every reason the verdict fell short, not just the first.
            payload["reasons"] = [*payload["reasons"], "DOES_NOT_BEAT_BASELINES"]
            if payload["verdict"] == str(EdgeVerdict.EDGE_DETECTED):
                payload["verdict"] = str(EdgeVerdict.NO_EDGE)
                payload["edge"] = False
        return payload
