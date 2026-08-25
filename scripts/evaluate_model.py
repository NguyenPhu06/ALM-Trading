from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from ai.datasets import ModelDatasetLoader
from ai.evaluation import evaluate_model
from ai.models import DecisionStumpBaseline, MajorityClassBaseline, SoftmaxLogisticBaseline
from ai.models.registry import ImmutableModelRegistry
from ai.training.imbalance import CLASS_NAMES, analyze_class_imbalance
from config.settings import ROOT, load_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare immutable Phase 5 model with TRAIN-only baselines")
    parser.add_argument("model_version")
    parser.add_argument("metadata")
    parser.add_argument("--models", default=str(ROOT / "data" / "models"))
    args = parser.parse_args()
    try:
        registry = ImmutableModelRegistry(args.models)
        neural, metadata = registry.load(args.model_version)
        dataset = ModelDatasetLoader().load(args.metadata)
        if dataset.dataset_version != metadata.dataset_version or dataset.feature_version != metadata.feature_version:
            raise ValueError("model and evaluation dataset versions differ")
        config = neural.config
        imbalance = analyze_class_imbalance(dataset.train.labels)
        class_weights = np.asarray([imbalance.class_weights[name] for name in CLASS_NAMES]) if config.class_weighting else None
        models = {
            "majority": MajorityClassBaseline().fit(dataset.train.matrix, dataset.train.labels),
            "logistic": SoftmaxLogisticBaseline().fit(dataset.train.matrix, dataset.train.labels, config=config, class_weights=class_weights),
            "tree_stump": DecisionStumpBaseline().fit(dataset.train.matrix, dataset.train.labels),
            "neural_network": neural,
        }
        bins = int(load_yaml().get("phase_5", {}).get("calibration_bins", 10))
        evaluations = {
            name: evaluate_model(
                model.model_version, dataset.test.labels, model.predict_proba(dataset.test.matrix),
                dataset.test.outcomes, calibration_bins=bins,
            )
            for name, model in models.items()
        }
        neural_score = evaluations["neural_network"].classification.balanced_accuracy
        baseline_score = max(value.classification.balanced_accuracy for key, value in evaluations.items() if key != "neural_network")
        payload = ImmutableModelRegistry._jsonable(evaluations)
        print(json.dumps({
            "status": "EVALUATION COMPLETE", "comparison": payload,
            "result": "NEURAL NETWORK BEATS BASELINE" if neural_score > baseline_score else "NEURAL NETWORK DOES NOT BEAT BASELINE",
            "disclaimer": "TEST_SET_USED_FOR_FINAL_EVALUATION_NOT_HYPERPARAMETER_TUNING",
        }, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "EVALUATION FAILED", "reasons": [type(exc).__name__, str(exc)]}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
