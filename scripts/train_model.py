from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.datasets import DatasetReadinessChecker, ModelDatasetLoader
from ai.models.registry import ImmutableModelRegistry
from ai.training.config import TrainingConfig
from ai.training.experiments import JsonExperimentTracker
from ai.training.trainer import ResearchTrainer
from config.settings import ROOT, load_yaml


def _latest_metadata(directory: Path) -> Path | None:
    candidates = sorted(directory.glob("*_dataset_metadata.json"))
    return candidates[-1] if candidates else None


def main() -> int:
    phase = load_yaml().get("phase_5", {})
    parser = argparse.ArgumentParser(description="Train the Phase 5 research-only three-class model")
    parser.add_argument("metadata", nargs="?", default=None)
    parser.add_argument("--models", default=str(ROOT / "data" / "models"))
    parser.add_argument("--experiments", default=str(ROOT / "data" / "experiments"))
    args = parser.parse_args()
    metadata_path = Path(args.metadata) if args.metadata else _latest_metadata(ROOT / "data" / "ml")
    minimum_samples = int(phase.get("minimum_dataset_samples", 1000))
    if metadata_path is None:
        print(json.dumps({"status": "TRAINING REFUSED", "reasons": ["DATASET NOT READY", "MISSING_DATASET"]}, indent=2))
        return 2
    readiness = DatasetReadinessChecker(minimum_samples=minimum_samples).check_files(metadata_path)
    if not readiness.ready:
        print(json.dumps({"status": "TRAINING REFUSED", "reasons": list(readiness.reasons)}, indent=2))
        return 2
    try:
        dataset = ModelDatasetLoader().load(metadata_path)
        config = TrainingConfig.from_yaml()
        report = ResearchTrainer(config, calibration_bins=int(phase["calibration_bins"])).train(dataset)
        registry = ImmutableModelRegistry(args.models)
        registry_metadata = registry.metadata_from_training(report, dataset)
        model_path = registry.register(report.model, registry_metadata)
        metrics = {
            "evaluations": ImmutableModelRegistry._jsonable(report.evaluations),
            "training_history": ImmutableModelRegistry._jsonable(report.history),
            "overfitting_status": report.history.overfitting_status,
        }
        experiment = JsonExperimentTracker(args.experiments).record(
            model_version=report.model_version, dataset_version=report.dataset_version,
            feature_version=report.feature_version, features=dataset.feature_names,
            hyperparameters=config.as_dict(), metrics=metrics,
        )
        print(json.dumps({
            "status": "TRAINING COMPLETE", "model_version": report.model_version,
            "model_path": str(model_path), "experiment_id": experiment.experiment_id,
            "overfitting_status": report.history.overfitting_status,
            "class_imbalance": ImmutableModelRegistry._jsonable(report.imbalance),
            "neural_network_beats_baseline": report.neural_network_beats_baseline,
            "result": "NEURAL NETWORK BEATS BASELINE" if report.neural_network_beats_baseline else "NEURAL NETWORK DOES NOT BEAT BASELINE",
            "metrics": metrics,
        }, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "TRAINING FAILED", "reasons": [type(exc).__name__, str(exc)]}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
